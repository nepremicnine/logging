from fastapi import FastAPI, HTTPException, Depends
from fastapi.routing import APIRoute
from models import SearchLog, VisitedLog
from auth_handler import verify_jwt_token, get_supabase_client
from dotenv import load_dotenv
import os
import requests
import pybreaker
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, RetryError

# Load environment variables
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_GRAPHQL_URL = f"{SUPABASE_URL}/graphql/v1"
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

LOGGING_API_SERVER_PORT = os.getenv("LOGGING_API_SERVER_PORT", "8080")
LOGGING_API_SERVER_MODE = os.getenv("LOGGING_API_SERVER_MODE", "development")
LOGGING_API_PREFIX = f"/logging" if LOGGING_API_SERVER_MODE == "production" else ""

app = FastAPI()

# Add prefix to all routes dynamically
def add_prefix_to_routes(app: FastAPI, prefix: str):
    """Add a prefix to all API routes."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            route.path = f"{prefix}{route.path}"

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

# Insert a search log
@app.post("/search_log")
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
@app.post("/visited_log")
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

# Add prefix to all routes
add_prefix_to_routes(app, LOGGING_API_PREFIX)