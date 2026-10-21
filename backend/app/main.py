import json
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal
from datetime import datetime
from uuid import UUID
from .facilities import get_facility_client, nearby_facilities, find_facility
from .walking import get_walking_provider
from .recommendations import recommend, get_closure_calendar
from .admin import router as admin_router
from .routes_proxy import router as routes_proxy_router

JSON_BODY_LIMIT_BYTES = 256 * 1024
MAX_JSON_NESTING = 64


def json_exceeds_nesting_limit(body, limit=MAX_JSON_NESTING):
    depth, in_string, escaped = 0, False, False
    for byte in body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):  # { [
            depth += 1
            if depth > limit:
                return True
        elif byte in (0x7D, 0x5D):  # } ]
            depth -= 1
    return False


class BoundedJSONBodyMiddleware:
    """Bound and parse JSON before FastAPI sees bodies on JSON POST endpoints."""

    def __init__(self, app, limit=JSON_BODY_LIMIT_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        guarded = (scope["type"] == "http" and scope["method"] == "POST" and
                   (path == "/api/aeds/recommendations" or path.startswith("/api/admin/")))
        if not guarded:
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        length = headers.get(b"content-length")
        if length:
            try:
                if int(length) > self.limit:
                    await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
                return
        content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if content_type != b"application/json":
            await JSONResponse({"detail": "Content-Type must be application/json"}, status_code=415)(scope, receive, send)
            return

        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.limit:
                await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                return
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        if json_exceeds_nesting_limit(body):
            await JSONResponse({"detail": [{"loc": ["body"], "msg": "JSON nesting limit exceeded", "type": "json_invalid"}]}, status_code=422)(scope, receive, send)
            return
        try:
            json.loads(body)
        except (json.JSONDecodeError, RecursionError, ValueError):
            await JSONResponse({"detail": [{"loc": ["body"], "msg": "JSON body is invalid", "type": "json_invalid"}]}, status_code=422)(scope, receive, send)
            return

        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.app(scope, replay, send)


app = FastAPI(title="LifeTime API", version="0.1.0")
app.add_middleware(BoundedJSONBodyMiddleware)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, exc: RequestValidationError):
    safe = []
    for error in exc.errors():
        loc = [part if isinstance(part, (str, int)) else "body" for part in error.get("loc", ())]
        safe.append({"loc": loc, "msg": "Invalid request value", "type": error.get("type", "value_error")})
    return JSONResponse(status_code=422, content={"detail": safe})
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
    model_config = ConfigDict(extra="forbid")
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def strict_coordinate(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("coordinate must be numeric")
        return value

class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: Position
    departure_at: datetime  # Requires timezone offset

    @field_validator("departure_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("departure_at must include timezone offset")
        return value

    @field_validator("departure_at", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("departure_at must be an ISO 8601 string")
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
