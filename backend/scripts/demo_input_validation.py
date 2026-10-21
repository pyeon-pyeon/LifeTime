"""Replay the API input-validation demo against FastAPI with synthetic services."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app.facilities import get_facility_client
from app.main import JSON_BODY_LIMIT_BYTES, app
from app.walking import get_walking_provider


FACILITY_ID = "00000000-0000-0000-0000-000000000001"
ACTOR_ID = "00000000-0000-0000-0000-000000000002"
REQUEST_ID = "00000000-0000-0000-0000-000000000003"
SYNTHETIC_TOKEN = "demo-only-token"


def record(**changes):
    result = {
        "facility_type": "aed", "source_id": "DEMO-SYNTHETIC-1",
        "name": "합성 시연 시설", "address": "합성 주소",
        "latitude": 37.5, "longitude": 127.0,
        "source_updated_at": None, "data_collected_at": "2026-10-21T09:00:00+09:00",
        "source_name": "synthetic demo", "contact_phone": None,
        "emergency_phone": None, "installation_detail": None,
        "schedule_status": "known", "sido": "서울", "gugun": "중구",
        "access_hours": [
            {"weekday": day, "opens_at": "09:00", "closes_at": "18:00",
             "ends_next_day": False, "is_24_hours": False}
            for day in range(1, 8)
        ],
    }
    result.update(changes)
    return result


class MockDatabase:
    role = "admin"

    def __init__(self):
        self.rpc_calls = 0
        self.auth_calls = 0
        self.auth = SimpleNamespace(get_user=self.get_user)

    def get_user(self, token):
        self.auth_calls += 1
        return SimpleNamespace(user=SimpleNamespace(
            id=ACTOR_ID, app_metadata={"role": self.role},
            user_metadata={"role": "admin"},
        ))

    def rpc(self, name, params):
        self.rpc_calls += 1
        return self

    def execute(self):
        return SimpleNamespace(data={"id": FACILITY_ID, "status": "pending"})


class MockRouteProvider:
    calls = 0

    def route(self, *args):
        self.calls += 1
        raise AssertionError("demo must not contact a route provider")


def main():
    database, route = MockDatabase(), MockRouteProvider()
    app.dependency_overrides[get_facility_client] = lambda: database
    app.dependency_overrides[get_walking_provider] = lambda: route
    headers = {"Authorization": f"Bearer {SYNTHETIC_TOKEN}"}
    results = []
    try:
        with TestClient(app) as client:
            endpoint = f"/api/admin/facilities/{FACILITY_ID}/changes"

            def run(label, response, expected, rpc_expected):
                assert response.status_code == expected, (label, response.status_code, response.text)
                assert database.rpc_calls == rpc_expected, (label, database.rpc_calls)
                assert route.calls == 0
                results.append((label, response.status_code, database.rpc_calls, route.calls))

            body = {"request_id": REQUEST_ID, "record": record()}
            run("정상 요청", client.post(endpoint, headers=headers, json=body), 200, 1)
            bad = {"request_id": REQUEST_ID, "record": record(latitude=91)}
            run("잘못된 좌표", client.post(endpoint, headers=headers, json=bad), 422, 1)
            bad = {"request_id": REQUEST_ID, "record": record(role="admin", approved=True)}
            run("추가 권한 필드", client.post(endpoint, headers=headers, json=bad), 422, 1)
            bad_record = record(schedule_status="partial", access_hours=[])
            run("모순된 운영시간", client.post(endpoint, headers=headers,
                json={"request_id": REQUEST_ID, "record": bad_record}), 422, 1)

            oversized = json.dumps({"padding": "x" * JSON_BODY_LIMIT_BYTES}).encode()
            run("본문 크기 초과", client.post("/api/aeds/recommendations", content=oversized,
                headers={"Content-Type": "application/json"}), 413, 1)

            database.role = "member"
            run("일반 사용자 관리자 접근", client.post(endpoint, headers=headers, json=body), 403, 1)
        print("case | status | facility_rpc_total | route_provider_total")
        for row in results:
            print(" | ".join(map(str, row)))
        print(f"관리자 인증 조회(Mock): {database.auth_calls}회")
        print("시설 DB/RPC 및 경로 공급자는 Mock이며 외부 서비스에 연결하지 않았습니다.")
    finally:
        app.dependency_overrides.clear()


if __name__ == "__main__":
    main()
