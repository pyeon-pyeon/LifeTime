import asyncio
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app import main as main_module
from app import routes_proxy
from app.facilities import get_facility_client
from app.main import app
from app.recommendations import get_closure_calendar
from app.rate_limit import (
    MemorySlidingWindowStore,
    RateLimitMiddleware,
    RateLimitPolicy,
    RateLimitUnavailable,
    UpstashRedisRestStore,
    client_ip_from_scope,
    hashed_client_key,
    normalize_ip,
    policy_and_store_from_env,
)
from app.walking import get_walking_provider


def _recommendation_payload():
    return {
        "start": {"latitude": 37.5, "longitude": 127.0},
        "departure_at": "2026-10-21T12:00:00+09:00",
    }


def _route_params():
    return {"start_x": 127, "start_y": 37, "end_x": 127.1, "end_y": 37.1}


def _set_limit(limit, clock, *, proxy="peer"):
    app.state.rate_limit_policy = RateLimitPolicy(
        limit=limit,
        window_ms=60_000,
        hmac_secret=b"test-only-rate-limit-secret-32-bytes",
        trusted_proxy=proxy,
    )
    app.state.rate_limit_store = MemorySlidingWindowStore(clock=clock)
    app.state.rate_limit_config_error = None


def _clients(*ips):
    return [TestClient(app, client=(ip, 12000 + index)) for index, ip in enumerate(ips)]


def _install_endpoint_spies(monkeypatch):
    calls = {"route": 0, "db": 0, "provider": 0, "calendar": 0, "recommend": 0}

    async def fake_request_route(*args, **kwargs):
        calls["route"] += 1
        return JSONResponse({"status": "OK", "route": {"properties": {}}})

    monkeypatch.setattr(routes_proxy, "request_route", fake_request_route)
    monkeypatch.setattr(
        main_module,
        "recommend",
        lambda *args, **kwargs: calls.__setitem__("recommend", calls["recommend"] + 1)
        or {"recommendations": [], "count": 0},
    )

    def fake_db():
        calls["db"] += 1
        return object()

    def fake_provider():
        calls["provider"] += 1
        return object()

    def fake_calendar():
        calls["calendar"] += 1
        return None

    app.dependency_overrides[get_facility_client] = fake_db
    app.dependency_overrides[get_walking_provider] = fake_provider
    app.dependency_overrides[get_closure_calendar] = fake_calendar
    return calls


def test_ten_allowed_then_shared_eleventh_is_429_before_endpoints(monkeypatch, local_rate_limit_runtime):
    _set_limit(10, local_rate_limit_runtime)
    calls = _install_endpoint_spies(monkeypatch)
    try:
        with TestClient(app, client=("203.0.113.10", 12000)) as client:
            for index in range(9):
                path = "/api/dev/walking-route" if index % 2 == 0 else "/api/dev/driving-route"
                response = client.get(
                    path,
                    params={"start_x": 127, "start_y": 37, "end_x": 127.1, "end_y": 37.1},
                )
                assert response.status_code == 200

            accepted = client.post("/api/aeds/recommendations", json=_recommendation_payload())
            assert accepted.status_code == 200
            assert calls["route"] == 9
            assert calls["db"] == calls["provider"] == calls["calendar"] == calls["recommend"] == 1

            blocked = client.post("/api/aeds/recommendations", json={"invalid": "body"})
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "60"
            assert blocked.headers["Cache-Control"] == "no-store"
            assert blocked.headers["X-RateLimit-Source"] == "lifetime"
            assert calls["route"] == 9
            assert calls["db"] == calls["provider"] == calls["calendar"] == calls["recommend"] == 1
    finally:
        app.dependency_overrides.clear()


def test_independent_ip_and_untrusted_forwarded_header_ignored(local_rate_limit_runtime):
    _set_limit(2, local_rate_limit_runtime)
    first, second = _clients("203.0.113.10", "203.0.113.20")
    try:
        for _ in range(2):
            assert first.get("/api/dev/walking-route", params=_route_params(), headers={"X-Forwarded-For": "203.0.113.20"}).status_code == 503
        assert first.get("/api/dev/walking-route", params=_route_params()).status_code == 429
        # The spoofed header did not consume the second client's bucket.
        assert second.get("/api/dev/walking-route", params=_route_params()).status_code == 503
    finally:
        first.close()
        second.close()


def test_sliding_window_retry_after_and_reopens_at_expiry(monkeypatch, local_rate_limit_runtime):
    _set_limit(1, local_rate_limit_runtime)
    _install_endpoint_spies(monkeypatch)
    with TestClient(app, client=("203.0.113.10", 12000)) as client:
        first = client.get("/api/dev/walking-route", params=_route_params())
        blocked = client.get("/api/dev/walking-route", params=_route_params())
        assert first.status_code == 200
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "60"

        local_rate_limit_runtime.advance(1)
        still_blocked = client.get("/api/dev/walking-route", params=_route_params())
        assert still_blocked.status_code == 429
        assert still_blocked.headers["Retry-After"] == "59"

        local_rate_limit_runtime.advance(59)
        reopened = client.get("/api/dev/walking-route", params=_route_params())
        assert reopened.status_code == 200


def test_options_and_health_do_not_consume_budget(local_rate_limit_runtime):
    _set_limit(1, local_rate_limit_runtime)
    with TestClient(app, client=("203.0.113.10", 12000)) as client:
        client.options("/api/dev/walking-route")
        assert client.get("/health").status_code == 200
        assert client.get("/api/dev/walking-route", params=_route_params()).status_code == 503
        assert client.get("/api/dev/walking-route", params=_route_params()).status_code == 429


def test_preflight_is_exempt_and_429_exposes_retry_after(local_rate_limit_runtime):
    _set_limit(1, local_rate_limit_runtime)
    origin = "http://localhost:5174"
    with TestClient(app, client=("203.0.113.10", 12000)) as client:
        preflight = client.options(
            "/api/dev/walking-route",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )
        assert preflight.status_code == 200
        assert client.get(
            "/api/dev/walking-route", params=_route_params(), headers={"Origin": origin}
        ).status_code == 503
        blocked = client.get(
            "/api/dev/walking-route", params=_route_params(), headers={"Origin": origin}
        )
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers["Access-Control-Expose-Headers"].lower()


def test_validation_precedes_endpoint_work_but_limit_precedes_validation(monkeypatch, local_rate_limit_runtime):
    _set_limit(10, local_rate_limit_runtime)
    calls = _install_endpoint_spies(monkeypatch)
    with TestClient(app, client=("203.0.113.10", 12000)) as client:
        for _ in range(10):
            response = client.post("/api/aeds/recommendations", json={"invalid": "body"})
            assert response.status_code == 422
        blocked = client.post("/api/aeds/recommendations", json={"invalid": "body"})
        assert blocked.status_code == 429
        # FastAPI resolves dependency factories before model validation, but the
        # recommendation function (which performs the actual facility/provider work)
        # is never reached for these invalid bodies.
        assert calls["db"] == calls["provider"] == calls["calendar"] == 10
        assert calls["recommend"] == 0
    app.dependency_overrides.clear()


def test_rate_store_failure_fails_closed_before_route_provider(monkeypatch, local_rate_limit_runtime):
    calls = _install_endpoint_spies(monkeypatch)

    class BrokenStore:
        async def consume(self, *args):
            raise OSError("private store details")

    app.state.rate_limit_store = BrokenStore()
    with TestClient(app, client=("203.0.113.10", 12000)) as client:
        response = client.get("/api/dev/walking-route", params=_route_params())
    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limit service unavailable"}
    assert "private store details" not in response.text
    assert calls["route"] == calls["db"] == calls["provider"] == calls["recommend"] == 0
    app.dependency_overrides.clear()


def test_ipv4_ipv6_normalization_and_trusted_vercel_header(local_rate_limit_runtime):
    assert normalize_ip("203.0.113.1") == "203.0.113.1"
    assert normalize_ip("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"
    assert normalize_ip("::ffff:203.0.113.1") == "203.0.113.1"

    scope = {"headers": [(b"x-forwarded-for", b"2001:db8::1")], "client": ("10.0.0.1", 1)}
    assert client_ip_from_scope(scope, "vercel") == "2001:db8::1"
    with pytest.raises(ValueError):
        client_ip_from_scope({"headers": [(b"x-forwarded-for", b"203.0.113.1, 10.0.0.1")]}, "vercel")
    with pytest.raises(ValueError):
        client_ip_from_scope({"headers": []}, "vercel")
    policy = RateLimitPolicy(10, 60_000, b"test-only-rate-limit-secret-32-bytes", "peer")
    assert "203.0.113.1" not in hashed_client_key(policy, "203.0.113.1")


def test_production_missing_shared_store_or_ip_config_fails_closed(monkeypatch, local_rate_limit_runtime):
    monkeypatch.setenv("VERCEL_ENV", "production")
    for name in (
        "RATE_LIMIT_STORE",
        "RATE_LIMIT_TRUSTED_PROXY",
        "RATE_LIMIT_HMAC_SECRET",
        "UPSTASH_REDIS_REST_URL",
        "UPSTASH_REDIS_REST_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    policy, store, error = policy_and_store_from_env()
    assert policy is None
    assert error
    app.state.rate_limit_policy = policy
    app.state.rate_limit_store = store
    app.state.rate_limit_config_error = error
    with TestClient(app, client=("203.0.113.10", 12000)) as client:
        response = client.get("/api/dev/walking-route", params=_route_params())
    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limit service unavailable"}


def test_local_store_and_limits_require_explicit_local_configuration(monkeypatch):
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RATE_LIMIT_STORE", "memory")
    monkeypatch.setenv("RATE_LIMIT_TRUSTED_PROXY", "peer")
    monkeypatch.setenv("RATE_LIMIT_LIMIT", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "7")
    monkeypatch.setenv("RATE_LIMIT_HMAC_SECRET", "local-development-secret-32-bytes!")
    policy, store, error = policy_and_store_from_env()
    assert error is None
    assert policy.limit == 3
    assert policy.window_ms == 7000
    assert isinstance(store, MemorySlidingWindowStore)


def test_upstream_provider_429_has_distinct_source_header(monkeypatch, local_rate_limit_runtime):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-only-never-printed")

    class FakeResponse:
        status_code = 429
        is_success = False

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.routes_proxy.httpx.AsyncClient", FakeAsyncClient)
    response = asyncio.run(routes_proxy.request_route("walking", 127, 37, 127.1, 37.1))
    assert response.status_code == 429
    assert response.headers["X-RateLimit-Source"] == "upstream"
    assert response.headers["Cache-Control"] == "no-store"


def test_two_app_instances_share_atomic_local_test_store(local_rate_limit_runtime):
    clock = local_rate_limit_runtime
    store = MemorySlidingWindowStore(clock=clock)
    policy = RateLimitPolicy(10, 60_000, b"test-only-rate-limit-secret-32-bytes", "peer")

    def instance():
        candidate = FastAPI()
        candidate.state.rate_limit_policy = policy
        candidate.state.rate_limit_store = store
        candidate.state.rate_limit_config_error = None
        candidate.add_middleware(RateLimitMiddleware, runtime_state=candidate.state)

        @candidate.get("/api/dev/walking-route")
        async def route():
            return {"ok": True}

        return candidate

    apps = [instance(), instance()]

    async def send_burst():
        async def send(index):
            transport = httpx.ASGITransport(app=apps[index % 2], client=("203.0.113.55", 4000 + index))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/dev/walking-route")

        responses = await asyncio.gather(*(send(index) for index in range(30)))
        return [response.status_code for response in responses]

    statuses = asyncio.run(send_burst())
    assert statuses.count(200) == 10
    assert statuses.count(429) == 20


def test_upstash_rest_adapter_uses_one_atomic_eval_and_rejects_bad_response(monkeypatch):
    captured = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": [0, 17]}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            captured.append(("timeout", kwargs["timeout"]))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json, headers):
            captured.append((url, json, headers))
            return FakeResponse()

    monkeypatch.setattr("app.rate_limit.httpx.AsyncClient", FakeAsyncClient)
    store = UpstashRedisRestStore("https://example.upstash.io", "never-printed-test-token")
    allowed, retry_after = asyncio.run(store.consume("hashed-key", 10, 60_000, "member"))
    assert (allowed, retry_after) == (False, 17)
    assert captured[1][1][0:3] == ["EVAL", captured[1][1][1], "1"]
    assert captured[1][1][3:] == ["hashed-key", "60000", "10", "member"]
    assert captured[1][2] == {"Authorization": "Bearer never-printed-test-token"}

    class BadResponse(FakeResponse):
        def json(self):
            return {"result": "not-an-array"}

    class BadClient(FakeAsyncClient):
        async def post(self, *args, **kwargs):
            return BadResponse()

    monkeypatch.setattr("app.rate_limit.httpx.AsyncClient", BadClient)
    with pytest.raises(RateLimitUnavailable):
        asyncio.run(store.consume("hashed-key", 10, 60_000, "member"))
