from pydantic import BaseModel
from typing import Optional

class SearchLog(BaseModel):
    user_id: str
    search_query: str
    location: str
    location_lat: float
    location_long: float
    location_max_dist: int
    types: list[str]
    price_min: int
    price_max: int
    size_min: int
    size_max: int

class VisitedLog(BaseModel):
    user_id: str
    property_id: str