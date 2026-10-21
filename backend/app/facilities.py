"""Read facilities from Supabase; never expose SDK errors or credentials."""

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from scripts.supabase_rest import create_supabase_client


logger = logging.getLogger(__name__)


def get_facility_client():
    try:
        return create_supabase_client()
    except Exception as exc:
        logger.error("facility_database_client_unavailable error_type=%s", type(exc).__name__)
        raise HTTPException(503, "Facility database unavailable") from None


def serialize_facility(row):
    result = {key: value for key, value in row.items() if key != "location"}
    for field in ("source_updated_at", "data_collected_at", "created_at", "updated_at"):
        value = result.get(field)
        if value:
            result[field] = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                ZoneInfo("Asia/Seoul")
            ).isoformat()
    return result


def nearby_facilities(client, latitude, longitude, facility_type, radius_m):
    try:
        response = client.rpc("nearby_facilities", {
            "p_latitude": latitude,
            "p_longitude": longitude,
            "p_facility_type": facility_type,
            "p_radius_m": radius_m,
        }).execute()
        rows = [serialize_facility(row) for row in response.data]
        return {"facilities": rows, "count": len(rows)}
    except Exception as exc:
        logger.error("facility_nearby_query_failed error_type=%s", type(exc).__name__)
        raise HTTPException(503, "Facility database unavailable") from None


def find_facility(client, facility_id):
    try:
        response = client.table("facilities").select(
            "*,access_hours:facility_access_hours(*)"
        ).eq("id", str(facility_id)).limit(1).execute()
        rows = response.data
        result = serialize_facility(rows[0]) if rows else None
    except Exception as exc:
        logger.error("facility_detail_query_failed error_type=%s", type(exc).__name__)
        raise HTTPException(503, "Facility database unavailable") from None
    if result is None:
        raise HTTPException(404, "Facility not found")
    result["access_hours"] = sorted(result.get("access_hours") or [], key=lambda h: h["weekday"])
    return result
