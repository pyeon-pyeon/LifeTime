from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from datetime import datetime
from uuid import UUID
from .facilities import get_facility_client, nearby_facilities, find_facility
from .walking import get_walking_provider
from .recommendations import recommend, get_closure_calendar
from .admin import router as admin_router
from .routes_proxy import router as routes_proxy_router

app = FastAPI(title="LifeTime API", version="0.1.0")
app.include_router(admin_router)
app.include_router(routes_proxy_router)
# For development only. Set explicit allowed origins before deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

FacilityType = Literal["aed", "emergency_room"]

class Position(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

class RecommendationRequest(BaseModel):
    start: Position
    departure_at: datetime  # Requires timezone offset

    @field_validator("departure_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("departure_at must include timezone offset")
        return value

class RecommendationItem(BaseModel):
    facility_id: UUID
    distance_m: float = Field(ge=0, allow_inf_nan=False)
    duration_sec: float = Field(ge=0, allow_inf_nan=False)
    arrival_at: datetime
    availability: Literal["available", "unavailable", "unknown"]

class RecommendationResponse(BaseModel):
    recommendations: list[RecommendationItem]
    count: int

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/facilities/nearby")
def nearby(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180),
           facility_type: FacilityType | None = None, radius_m: int = Query(default=3000, ge=1, le=20000),
           client=Depends(get_facility_client)):
    return nearby_facilities(client, latitude, longitude, facility_type, radius_m)

@app.get("/api/facilities/{id}")
def facility_detail(id: str, client=Depends(get_facility_client)):
    try:
        facility_id = UUID(id)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(404, "Facility not found") from None
    return find_facility(client, facility_id)

@app.post("/api/aeds/recommendations", response_model=RecommendationResponse)
def recommendations(request: RecommendationRequest, provider=Depends(get_walking_provider),
                    client=Depends(get_facility_client), calendar=Depends(get_closure_calendar)):
    return recommend(client, provider, request, calendar=calendar)
