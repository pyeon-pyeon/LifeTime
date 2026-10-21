import pytest

from app.main import app
from app.rate_limit import MemorySlidingWindowStore, RateLimitPolicy


class TestClock:
    def __init__(self, value=1_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture(autouse=True)
def local_rate_limit_runtime(monkeypatch):
    """Give every test an isolated explicit local store; never use a real Redis."""
    app.dependency_overrides.clear()
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.delenv("TMAP_API_KEY", raising=False)
    clock = TestClock()
    app.state.rate_limit_policy = RateLimitPolicy(
        limit=10,
        window_ms=60_000,
        hmac_secret=b"test-only-rate-limit-secret-32-bytes",
        trusted_proxy="peer",
    )
    app.state.rate_limit_store = MemorySlidingWindowStore(clock=clock)
    app.state.rate_limit_config_error = None
    yield clock
    app.dependency_overrides.clear()
