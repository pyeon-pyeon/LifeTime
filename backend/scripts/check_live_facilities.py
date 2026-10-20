"""Read-only real Supabase API smoke test. Uses no dependency overrides or mocks.

Run from backend: python -m scripts.check_live_facilities
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from scripts.supabase_rest import create_supabase_client


def main():
    try:
        database = create_supabase_client()
        count = database.table("facilities").select(
            "id", count="exact", head=True
        ).eq("facility_type", "aed").execute().count
        print(f"Real Supabase REST exact AED count: {count}")
        sample = database.table("facilities").select(
            "id,latitude,longitude"
        ).eq("facility_type", "aed").not_.is_("latitude", "null").not_.is_(
            "longitude", "null"
        ).limit(1).execute().data
        if not sample:
            raise RuntimeError("No real AED with coordinates; import is incomplete")
        row = sample[0]
        with TestClient(app) as client:
            response = client.get("/api/facilities/nearby", params={
                "latitude": row["latitude"], "longitude": row["longitude"],
                "facility_type": "aed", "radius_m": 100,
            })
            print(f"Real DB nearby HTTP status: {response.status_code}")
            assert response.status_code == 200
            payload = response.json()
            assert payload["count"] == len(payload["facilities"])
            assert any(f["id"] == row["id"] for f in payload["facilities"])
            assert all(f["facility_type"] == "aed" and 0 <= f["distance_m"] <= 100
                       for f in payload["facilities"])
            response = client.get(f'/api/facilities/{row["id"]}')
            print(f"Real DB detail HTTP status: {response.status_code}")
            assert response.status_code == 200
            assert response.json()["id"] == row["id"]
            response = client.get(f"/api/facilities/{uuid4()}")
            print(f"Real DB missing detail HTTP status: {response.status_code}")
            assert response.status_code == 404
        print("Real Supabase facility API smoke test passed.")
        return 0
    except Exception as error:
        print(f"Live verification incomplete ({type(error).__name__}); details hidden.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
