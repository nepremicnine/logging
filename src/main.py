from fastapi import FastAPI, HTTPException, Depends
from fastapi.routing import APIRoute
from src.models import SearchLog, VisitedLog
from src.auth_handler import verify_jwt_token, get_supabase_client
from dotenv import load_dotenv
import os
import requests
import pybreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaConsumer
import asyncio
import json
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Gauge, Summary
from time import time
from fastapi import FastAPI, HTTPException, Request

# Load environment variables
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_GRAPHQL_URL = f"{SUPABASE_URL}/graphql/v1"
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

LOGGING_SERVER_PORT = os.getenv("LOGGING_SERVER_PORT", "8080")
LOGGING_SERVER_MODE = os.getenv("LOGGING_SERVER_MODE", "development")
LOGGING_PREFIX = f"/logging" if LOGGING_SERVER_MODE == "release" else ""
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8080")

# Kafka Configuration
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "localhost")
KAFKA_PORT = os.getenv("KAFKA_PORT", "9092")
TOPICS = ["property-search-events", "property-click-events"]


executor = ThreadPoolExecutor(max_workers=1)

# Kafka Consumer Logic


def kafka_consumer_thread():
    try:
        consumer = KafkaConsumer(
            *TOPICS,
            bootstrap_servers=f"{KAFKA_BROKER}:{KAFKA_PORT}",
            group_id="logging-service-group",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )
        print("Kafka consumer started")
        for message in consumer:
            process_message_sync(message)
    except Exception as e:
        print(f"Error in Kafka consumer thread: {e}")

# Synchronous message processing function


def process_message_sync(message):
    try:
        topic = message.topic
        data = json.loads(message.value.decode("utf-8"))

        if topic == "property-search-events":
            print(f"Processing search event: {data}")
            supabase = get_supabase_client()
            supabase.table("search_log").insert({
                "user_id": data["userId"],
                "search_query": data["searchQuery"] if "searchQuery" in data else None,
                "location_lat": data["locationLat"] if "locationLat" in data else None,
                "location_long": data["locationLon"] if "locationLon" in data else None,
                "location_max_dist": data["locationMaxDistance"] if "locationMaxDistance" in data else None,
                "types": data["types"] if "types" in data else None,
                "price_min": data["priceMin"] if "priceMin" in data else None,
                "price_max": data["priceMax"] if "priceMax" in data else None,
                "size_min": data["sizeMin"] if "sizeMin" in data else None,
                "size_max": data["sizeMax"] if "sizeMax" in data else None,
            }).execute()
        elif topic == "property-click-events":
            print(f"Processing click event: {data}")
            supabase = get_supabase_client()
            supabase.table("visited_log").insert({
                "user_id": data["user_id"],
                "property_id": data["property_id"],
            }).execute()
    except Exception as e:
        print(f"Error processing Kafka message: {e}")

# Lifespan with Thread Management


@asynccontextmanager
async def lifespan(app: FastAPI):
    global executor
    # Start Kafka consumer in a separate thread
    executor.submit(kafka_consumer_thread)
    yield  # Application starts here
    # Shut down the ThreadPoolExecutor on app shutdown
    executor.shutdown(wait=True)


# Initialize FastAPI app with lifespan
app = FastAPI(
    title="Logging API",
    description="API for logging user search and visited properties",
    version="1.0.0",
    openapi_url=f"{LOGGING_PREFIX}/openapi.json",
    docs_url=f"{LOGGING_PREFIX}/docs",
    redoc_url=f"{LOGGING_PREFIX}/redoc",
    lifespan=lifespan,
)

origins = [
    FRONTEND_URL,
    BACKEND_URL,
    "http://localhost",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Prometheus instrumentator
Instrumentator().instrument(app).expose(app, endpoint=f"{LOGGING_PREFIX}/metrics")

# Additional custom metrics (if needed)
REQUEST_COUNT = Counter('request_count', 'Total number of requests', ['method', 'endpoint', 'status_code'])
REQUEST_LATENCY = Summary('request_latency_seconds', 'Latency of requests in seconds')

@app.middleware("http")
async def add_prometheus_metrics(request: Request, call_next):
    start_time = time()
    response = await call_next(request)
    process_time = time() - start_time

    # Record custom metrics
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code
    ).inc()

    REQUEST_LATENCY.observe(process_time)

    return response


# Circuit Breaker Configuration
breaker = pybreaker.CircuitBreaker(
    fail_max=5,  # Maximum number of failures before opening the circuit
    reset_timeout=30  # Time in seconds before attempting to reset the circuit
)

# Retry Configuration


def is_transient_error(exception):
    """Define what qualifies as a transient error."""
    return isinstance(exception, requests.exceptions.RequestException)


retry_strategy = retry(
    stop=stop_after_attempt(3),  # Retry up to 3 times
    # Exponential backoff: 2s, 4s, 6s
    wait=wait_exponential(multiplier=1, min=2, max=6),
    # Retry only on network-related errors
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)


# Insert a search log
@app.post(f"{LOGGING_PREFIX}/search_log")
async def insert_search_log(search_log: SearchLog):
    try:
        supabase = get_supabase_client()

        response = supabase.table("search_log").insert(
            [
                {
                    "user_id": search_log.user_id,
                    "search_query": search_log.search_query,
                    "location_lat": search_log.location_lat,
                    "location_long": search_log.location_long,
                    "location_max_dist": search_log.location_max_dist,
                    "types": search_log.types,
                    "price_min": search_log.price_min,
                    "price_max": search_log.price_max,
                    "size_min": search_log.size_min,
                    "size_max": search_log.size_max,
                }
            ]
        ).execute()

        return {"Log inserted": response}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Insert a visited log


@app.post(f"{LOGGING_PREFIX}/visited_log")
async def insert_visited_log(visited_log: VisitedLog):
    try:
        supabase = get_supabase_client()

        response = supabase.table("visited_log").insert(
            [
                {
                    "user_id": visited_log.user_id,
                    "property_id": visited_log.property_id,
                }
            ]
        ).execute()

        return {"Log inserted": response}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Health check


@app.get(f"{LOGGING_PREFIX}/health")
async def health_check():
    return {"status": "ok"}
