from pydantic import BaseModel, Field
from typing import List

class MatchRequest(BaseModel):
    rider_id: str = Field(..., description="Unique identifier for the rider")
    rider_lat: float = Field(..., description="Latitude of the rider")
    rider_lon: float = Field(..., description="Longitude of the rider")
    top_k: int = Field(5, description="Number of drivers to return", ge=1)

class MatchResponseItem(BaseModel):
    driver_id: str
    score: float
    distance_km: float

class MatchResponse(BaseModel):
    matches: List[MatchResponseItem]
