"""Input security regressions use only synthetic fixtures and mocked services."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.facilities import get_facility_client
from app.main import JSON_BODY_LIMIT_BYTES, BoundedJSONBodyMiddleware, MAX_JSON_NESTING, app
from app.walking import get_walking_provider


FID = "00000000-0000-0000-0000-000000000001"
ACTOR = "00000000-0000-0000-0000-000000000002"
REQUEST = "00000000-0000-0000-0000-000000000003"
TOKEN = "synthetic-admin-token"


def valid_record(**changes):
    record = {
        "facility_type": "aed", "source_id": " FIXTURE-1 ", "name": "Fixture",
        "address": None, "latitude": 37, "longitude": 127,
        "source_updated_at": "2026-10-21T09:00:00+09:00", "data_collected_at": None,
        "source_name": None, "contact_phone": None, "emergency_phone": None,
        "installation_detail": None, "schedule_status": "known", "sido": None,
        "gugun": None, "access_hours": [
            {"weekday": day, "opens_at": "22:00", "closes_at": "02:00",
             "ends_next_day": True, "is_24_hours": False} for day in range(1, 8)
        ],
    }
    record.update(changes)
    return record


class CountingServices:
    def __init__(self, role="admin"):
        self.role = role
        self.rpc_calls = []
        self.auth_calls = []
        self.auth = SimpleNamespace(get_user=self.get_user)

    def get_user(self, token):
        self.auth_calls.append(token)
        return SimpleNamespace(user=SimpleNamespace(
            id=ACTOR,
            app_metadata={"role": self.role},
            user_metadata={"role": "admin"},
        ))

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        self.last_rpc = name
        return self

    def execute(self):
        if self.last_rpc == "nearby_facilities":
            return SimpleNamespace(data=[])
        return SimpleNamespace(data={"status": "pending"})


class RouteCounter:
    def __init__(self): self.calls = 0
    def route(self, *args):
        self.calls += 1
        raise AssertionError("route provider must not run for invalid input")


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr("app.walking.load_dotenv", lambda *args, **kwargs: None)
    services, route = CountingServices(), RouteCounter()
    app.dependency_overrides[get_facility_client] = lambda: services
    app.dependency_overrides[get_walking_provider] = lambda: route
    with TestClient(app) as client:
        yield client, services, route
    app.dependency_overrides.clear()


def propose(client, record, *, extra=None, headers=None):
    body = {"request_id": REQUEST, "record": record}
    if extra:
        body.update(extra)
    return client.post(f"/api/admin/facilities/{FID}/changes",
                       headers=headers or {"Authorization": f"Bearer {TOKEN}"}, json=body)


def test_valid_admin_proposal_normalizes_values_and_preserves_rpc_contract(api):
    client, services, _ = api
    response = propose(client, valid_record())
    assert response.status_code == 200
    name, params = services.rpc_calls[0]
    assert name == "propose_facility_change"
    assert params["p_record"]["source_id"] == "FIXTURE-1"
    assert params["p_record"]["access_hours"][0]["opens_at"] == "22:00:00"
    assert params["p_record"]["source_updated_at"] == "2026-10-21T09:00:00+09:00"


@pytest.mark.parametrize("field,value", [
    ("latitude", 90.00001), ("latitude", True), ("longitude", -181),
    ("source_id", "  "), ("source_id", "x" * 201), ("name", "x" * 301),
    ("contact_phone", 100), ("contact_phone", "1" * 101),
    ("address", "x" * 1001), ("source_name", "x" * 1001),
    ("schedule_status", "closed"),
    ("facility_type", "hospital"),
    ("source_updated_at", 1792540800),
    ("source_updated_at", "2026-10-21T09:00:00"),
    ("data_collected_at", ""), ("latitude", ""),
])
def test_invalid_admin_field_never_calls_facility_rpc(api, field, value):
    client, services, _ = api
    response = propose(client, valid_record(**{field: value}))
    assert response.status_code == 422
    assert services.rpc_calls == []
    assert "input" not in response.text


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_number_is_rejected(api, token):
    client, services, _ = api
    body = json.dumps({"request_id": REQUEST, "record": valid_record()})
    body = body.replace("37", token, 1)
    response = client.post(f"/api/admin/facilities/{FID}/changes",
                           headers={"Authorization": f"Bearer {TOKEN}",
                                    "Content-Type": "application/json"}, content=body)
    assert response.status_code == 422 and services.rpc_calls == []


@pytest.mark.parametrize("record,top_extra", [
    (valid_record(role="admin"), None),
    (valid_record(approved=True), None),
    (valid_record(access_hours=[{**valid_record()["access_hours"][0], "role": "admin"}] ), None),
    (valid_record(), {"is_admin": True}),
    ({"source_id": "FIXTURE-1"}, None),
])
def test_extra_or_missing_fields_rejected_without_rpc(api, record, top_extra):
    client, services, _ = api
    response = propose(client, record, extra=top_extra)
    assert response.status_code == 422
    assert services.rpc_calls == []


@pytest.mark.parametrize("hours,status", [
    ([{**valid_record()["access_hours"][0], "weekday": True}] + valid_record()["access_hours"][1:], "known"),
    (valid_record()["access_hours"] + [valid_record()["access_hours"][0]], "known"),
    (valid_record()["access_hours"] + [dict(valid_record()["access_hours"][0], weekday=8)], "known"),
    ([dict(valid_record()["access_hours"][0], closes_at="08:00") for _ in range(7)], "known"),
    ([dict(valid_record()["access_hours"][0], ends_next_day=False) for _ in range(7)], "known"),
    ([], "known"),
    ([valid_record()["access_hours"][0]], "unknown"),
])
def test_inconsistent_schedule_rejected(api, hours, status):
    client, services, _ = api
    response = propose(client, valid_record(access_hours=hours, schedule_status=status))
    assert response.status_code == 422
    assert services.rpc_calls == []


def test_24_hour_schedule_and_json_numeric_boundaries_accepted(api):
    client, services, _ = api
    hours = [{"weekday": day, "opens_at": "00:00", "closes_at": "00:00",
              "ends_next_day": True, "is_24_hours": True} for day in range(1, 8)]
    response = propose(client, valid_record(latitude=-90, longitude=180, access_hours=hours))
    assert response.status_code == 200
    assert len(services.rpc_calls) == 1


def test_reason_is_trimmed_and_capped_and_invalid_action_keeps_404(api):
    client, services, _ = api
    body = {"request_id": REQUEST, "reason": "  checked  "}
    response = client.post(f"/api/admin/facility-changes/{FID}/approve",
                           headers={"Authorization": f"Bearer {TOKEN}"}, json=body)
    assert response.status_code == 200
    assert services.rpc_calls[0][1]["p_reason"] == "checked"
    body["reason"] = " " * 501
    response = client.post(f"/api/admin/facility-changes/{FID}/approve",
                           headers={"Authorization": f"Bearer {TOKEN}"}, json=body)
    assert response.status_code == 422
    assert len(services.rpc_calls) == 1
    response = client.post(f"/api/admin/facility-changes/{FID}/invent",
                           headers={"Authorization": f"Bearer {TOKEN}"}, json={"request_id": REQUEST, "reason": "ok"})
    assert response.status_code == 404


def test_public_invalid_uuid_keeps_existing_not_found_contract(api):
    client, services, _ = api
    response = client.get("/api/facilities/not-a-uuid")
    assert response.status_code == 404
    assert response.json() == {"detail": "Facility not found"}
    assert services.rpc_calls == []


def test_emergency_room_hours_are_rejected(api):
    client, services, _ = api
    response = propose(client, valid_record(facility_type="emergency_room",
        schedule_status=None, access_hours=[valid_record()["access_hours"][0]]))
    assert response.status_code == 422
    assert services.rpc_calls == []


def test_validation_errors_do_not_echo_secret_or_raw_body(api):
    client, services, _ = api
    payload = {"request_id": REQUEST, "record": valid_record(latitude="TOP-SECRET")}
    payload["private_token"] = "TOP-SECRET"
    response = client.post(f"/api/admin/facilities/{FID}/changes",
                           headers={"Authorization": "Bearer AUTH-SECRET"}, json=payload)
    assert response.status_code == 422
    for secret in ("TOP-SECRET", "AUTH-SECRET"):
        assert secret not in response.text
    assert services.rpc_calls == []


def test_invalid_recommendation_input_skips_facility_rpc_and_route(api):
    client, services, route = api
    response = client.post("/api/aeds/recommendations", json={
        "start": {"latitude": 37.5, "longitude": 127, "role": "admin"},
        "departure_at": "2026-10-21T09:00:00+09:00",
    })
    assert response.status_code == 422
    assert services.rpc_calls == [] and route.calls == 0


def test_recommendation_boolean_coordinate_and_numeric_timestamp_are_rejected(api):
    client, services, route = api
    base = {"start": {"latitude": 37.5, "longitude": 127},
            "departure_at": "2026-10-21T09:00:00+09:00"}
    for payload in [
        {**base, "start": {"latitude": True, "longitude": 127}},
        {**base, "departure_at": 1792540800},
    ]:
        response = client.post("/api/aeds/recommendations", json=payload)
        assert response.status_code == 422
    assert services.rpc_calls == [] and route.calls == 0


def test_query_accepts_numeric_strings_and_keeps_existing_radius_limit(api):
    client, services, _ = api
    response = client.get("/api/facilities/nearby?latitude=90&longitude=-180&radius_m=20000")
    assert response.status_code == 200
    assert services.rpc_calls == [("nearby_facilities", {
        "p_latitude": 90.0, "p_longitude": -180.0,
        "p_facility_type": None, "p_radius_m": 20000,
    })]
    response = client.get("/api/facilities/nearby?latitude=90&longitude=-180&radius_m=20001")
    assert response.status_code == 422 and len(services.rpc_calls) == 1


def test_admin_authentication_metadata_spoof_is_denied(api):
    client, services, _ = api
    services.role = "member"
    response = propose(client, valid_record())
    assert response.status_code == 403
    assert services.auth_calls == [TOKEN]
    assert services.rpc_calls == []


def test_body_validation_precedes_authentication_for_malformed_admin_json(api):
    client, services, _ = api
    response = client.post(f"/api/admin/facility-changes/{FID}/approve", json={"invalid": True})
    # Missing/invalid credentials take precedence over schema errors for valid JSON.
    assert response.status_code == 401
    assert services.auth_calls == [] and services.rpc_calls == []
    response = client.post(f"/api/admin/facility-changes/{FID}/approve",
                           headers={"Authorization": f"Bearer {TOKEN}"}, json={"invalid": True})
    assert response.status_code == 422
    assert services.auth_calls == [TOKEN] and services.rpc_calls == []
    response = client.post(f"/api/admin/facility-changes/{FID}/approve", content=b"{bad",
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert services.auth_calls == [TOKEN] and services.rpc_calls == []


def _body_of_size(size):
    prefix, suffix = b'{"extra":"', b'"}'
    return prefix + (b"x" * (size - len(prefix) - len(suffix))) + suffix


def test_body_size_limit_boundary_and_content_length_overflow(api):
    client, services, _ = api
    exact = _body_of_size(JSON_BODY_LIMIT_BYTES)
    response = client.post("/api/aeds/recommendations", content=exact,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    oversized = client.post("/api/aeds/recommendations", content=exact + b" ",
                            headers={"Content-Type": "application/json"})
    assert oversized.status_code == 413
    assert services.rpc_calls == []


def test_chunked_body_without_content_length_is_counted():
    body = b"{" + b" " * JSON_BODY_LIMIT_BYTES + b"}"
    chunks = [body[:100_000], body[100_000:200_000], body[200_000:]]
    state = {"index": 0, "sent": []}
    async def receive():
        index = state["index"]
        state["index"] += 1
        return {"type": "http.request", "body": chunks[index], "more_body": index < len(chunks) - 1}
    async def inner(scope, receive, send):
        raise AssertionError("oversized request must be rejected before the app")
    async def send(message): state["sent"].append(message)
    scope = {"type": "http", "method": "POST", "path": "/api/aeds/recommendations",
             "headers": [(b"content-type", b"application/json")]}
    asyncio.run(BoundedJSONBodyMiddleware(inner)(scope, receive, send))
    assert state["sent"][0]["status"] == 413


@pytest.mark.parametrize("body", [
    b"{invalid",
    b"{" + b"[" * (MAX_JSON_NESTING + 1) + b"0" + b"]" * (MAX_JSON_NESTING + 1) + b"}",
    b"{" + b"[" * 1100 + b"0" + b"]" * 1100 + b"}",
])
def test_bad_json_and_deep_json_return_422_not_500(api, body):
    client, services, _ = api
    response = client.post("/api/aeds/recommendations", content=body,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert services.rpc_calls == []


def test_unsupported_media_type_is_rejected(api):
    client, services, _ = api
    response = client.post("/api/aeds/recommendations", content="{}",
                           headers={"Content-Type": "text/plain"})
    assert response.status_code == 415
    assert services.rpc_calls == []
