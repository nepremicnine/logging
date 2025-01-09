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

# Create a Kafka consumer (initialized later)
consumer = None

# Lifespan context manager for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    global consumer
    consumer = KafkaConsumer(
        *TOPICS,
        bootstrap_servers=f"{KAFKA_BROKER}:{KAFKA_PORT}",
        group_id="logging-service-group",
        auto_offset_reset="earliest",  # Start consuming from the earliest message
        enable_auto_commit=True,
    )


    # Start the Kafka consumer
    loop = asyncio.get_event_loop()
    loop.create_task(consume_kafka_messages())

    yield  # Application starts here

    # Shutdown: close Kafka consumer
    consumer.close()

app = FastAPI(
    title="Logging API",
    description="API for logging user search and visited properties",
    version="1.0.0",
    openapi_url=f"{LOGGING_PREFIX}/openapi.json",
    docs_url=f"{LOGGING_PREFIX}/docs",
    redoc_url=f"{LOGGING_PREFIX}/redoc",
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
    wait=wait_exponential(multiplier=1, min=2, max=6),  # Exponential backoff: 2s, 4s, 6s
    retry=retry_if_exception_type(requests.exceptions.RequestException)  # Retry only on network-related errors
)


# Process Kafka messages
async def process_message(topic, message):
    """Handle messages based on topic."""
    key = message.key.decode("utf-8")
    data = json.loads(message.value.decode("utf-8"))
    if topic == "property-search-events":
        print(f"Processing search event: {data}")
        # Add logic to insert search logs into the database (Supabase)
        supabase = get_supabase_client()
        supabase.table("search_log").insert({
            "user_id": data["user_id"],
            "search_query": data["search_query"],
            "location_lat": data["location_lat"],
            "location_long": data["location_long"],
            "location_max_dist": data["location_max_dist"],
            "types": data["types"],
            "price_min": data["price_min"],
            "price_max": data["price_max"],
            "size_min": data["size_min"],
            "size_max": data["size_max"],
        }).execute()
    elif topic == "property-click-events":
        print(f"Processing click event: {data}")
        # Add logic to insert visited logs into the database (Supabase)
        supabase = get_supabase_client()
        supabase.table("visited_log").insert({
            "user_id": data["user_id"],
            "property_id": data["property_id"],
        }).execute()

# Process Kafka messages asynchronously
async def consume_kafka_messages():
    try:
        for message in consumer:
            await process_message(message.topic, message)
    except Exception as e:
        print(f"Error consuming Kafka messages: {e}")


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
