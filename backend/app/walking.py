"""Replaceable walking providers. Mock routes are injected only by tests."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from dotenv import load_dotenv


class RouteError(Exception):
    def __init__(self, category):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class WalkingRoute:
    distance_m: float
    duration_sec: float

    def __post_init__(self):
        for value in (self.distance_m, self.duration_sec):
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value) or value < 0:
                raise RouteError("invalid_response")
        if self.duration_sec > 7 * 86400:
            raise RouteError("invalid_response")


def check_position(position):
    try:
        latitude, longitude = position["latitude"], position["longitude"]
        if (isinstance(latitude, bool) or isinstance(longitude, bool)
                or not isfinite(latitude) or not isfinite(longitude)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise RouteError("invalid_coordinates") from None


class WalkingProvider(Protocol):
    def route(self, start: dict, destination: dict, departure_at: datetime) -> WalkingRoute: ...


class TmapWalkingProvider:
    def __init__(self, api_key, transport=None):
        if not api_key:
            raise RouteError("not_configured")
        self.api_key, self.transport = api_key, transport

    def route(self, start, destination, departure_at):
        check_position(start)
        check_position(destination)
        if departure_at.tzinfo is None or departure_at.utcoffset() is None:
            raise RouteError("invalid_departure")
        try:
            with httpx.Client(timeout=httpx.Timeout(10), transport=self.transport) as client:
                response = client.post(
                    "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1",
                    headers={"appKey": self.api_key, "Accept": "application/json"}, json={
                        "startX": start["longitude"], "startY": start["latitude"],
                        "endX": destination["longitude"], "endY": destination["latitude"],
                        "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
                        "startName": quote("출발지"), "endName": "AED", "speed": 5,
                    },
                )
            if response.status_code == 429:
                raise RouteError("rate_limited")
            if response.status_code in (401, 403):
                raise RouteError("authentication_failed")
            if response.status_code >= 400:
                raise RouteError("upstream_error")
            props = response.json()["features"][0]["properties"]
            return WalkingRoute(props["totalDistance"], props["totalTime"])
        except httpx.TimeoutException:
            raise RouteError("timeout") from None
        except httpx.RequestError:
            raise RouteError("network_error") from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise RouteError("invalid_response") from None


def get_walking_provider():
    # No environment switch silently enables a mock in the production API.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    key = os.getenv("TMAP_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Walking route provider not configured")
    return TmapWalkingProvider(key)


def route_http_error(error):
    status = {"timeout": 504, "rate_limited": 503, "not_configured": 503,
              "authentication_failed": 503, "invalid_coordinates": 422}.get(error.category, 502)
    return HTTPException(status, "Walking route " + error.category.replace("_", " "))
