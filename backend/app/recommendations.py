"""Recommendation orchestration using the existing Supabase facility readers."""

from fastapi import HTTPException

from .availability import evaluate_arrival
from .facilities import nearby_facilities, find_facility
from .walking import RouteError, route_http_error


def get_closure_calendar():
    # No holiday/temporary-closure data exists in the current schema. Never invent it.
    return None


def recommend(client, provider, request, *, calendar=None):
    start = request.start.model_dump()
    rows = nearby_facilities(client, start["latitude"], start["longitude"], "aed", 3000)["facilities"]
    results = []
    # Limit external calls per request, with nearest-first database ordering.
    for row in rows[:10]:
        facility = find_facility(client, row["id"])
        if facility["facility_type"] != "aed":
            continue
        if facility.get("latitude") is None or facility.get("longitude") is None:
            continue
        try:
            route = provider.route(start, facility, request.departure_at)
            first = evaluate_arrival(request.departure_at, route.duration_sec, facility.get("access_hours"),
                                     schedule_status=facility.get("schedule_status"))
            closure = calendar(facility["id"], first.arrival_at.date()) if calendar else None
            decision = evaluate_arrival(request.departure_at, route.duration_sec,
                                        facility.get("access_hours"), closure=closure,
                                        schedule_status=facility.get("schedule_status"))
        except RouteError as error:
            raise route_http_error(error) from None
        except (ValueError, OverflowError):
            raise HTTPException(502, "Invalid walking arrival time") from None
        results.append({"facility_id": facility["id"], "distance_m": route.distance_m,
                        "duration_sec": route.duration_sec,
                        "arrival_at": decision.arrival_at.isoformat(),
                        "availability": decision.availability})
    results.sort(key=lambda r: (r["duration_sec"], r["distance_m"], r["facility_id"]))
    return {"recommendations": results, "count": len(results)}
