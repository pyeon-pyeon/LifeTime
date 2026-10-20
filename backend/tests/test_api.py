from fastapi.testclient import TestClient
from app.main import app
from app.facilities import get_facility_client
from types import SimpleNamespace
import pytest


class FakeDatabase:
    def __init__(self, rows=None, error=False):
        self.rows = rows or []
        self.error = error
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def table(self, name):
        self.calls.append(('table', name))
        return self

    def select(self, fields):
        return self

    def eq(self, field, value):
        self.calls.append((field, value))
        return self

    def limit(self, size):
        return self

    def execute(self):
        if self.error:
            raise RuntimeError('secret-test-must-not-leak')
        return SimpleNamespace(data=self.rows)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    # Unit tests must not enable a real provider when a developer configures .env.
    monkeypatch.setattr('app.walking.load_dotenv', lambda *args, **kwargs: None)
    monkeypatch.delenv('TMAP_API_KEY', raising=False)
    fake = FakeDatabase()
    app.dependency_overrides[get_facility_client] = lambda: fake
    yield fake
    app.dependency_overrides.clear()

client = TestClient(app)

def test_health():
    assert client.get('/health').json() == {'status': 'ok'}

def test_nearby_empty_until_import():
    resp = client.get('/api/facilities/nearby', params={'latitude': 36.35, 'longitude': 127.38})
    assert resp.status_code == 200
    assert resp.json() == {'facilities': [], 'count': 0}

def test_invalid_facility_type_rejected():
    assert client.get('/api/facilities/nearby', params={'latitude': 36.35, 'longitude': 127.38, 'facility_type': 'hospital'}).status_code == 422

def test_recommendation_unconfigured():
    resp = client.post('/api/aeds/recommendations', json={'start': {'latitude': 36.35, 'longitude': 127.38}, 'departure_at': '2026-10-20T15:00:00+09:00'})
    assert resp.status_code == 503


@pytest.mark.parametrize('kind', ['aed', 'emergency_room', None])
def test_nearby_uses_database_and_meter_parameters(database, kind):
    database.rows = [{'id': 'fixture-only', 'facility_type': kind or 'aed',
                      'latitude': 37.5, 'longitude': 127.0, 'distance_m': 12.5,
                      'source_updated_at': None,
                      'data_collected_at': '2026-10-20T00:00:00Z'}]
    params = {'latitude': 37.5, 'longitude': 127.0, 'radius_m': 250}
    if kind:
        params['facility_type'] = kind
    response = client.get('/api/facilities/nearby', params=params)
    assert response.status_code == 200
    assert response.json()['count'] == 1
    row = response.json()['facilities'][0]
    assert row['distance_m'] == 12.5
    assert row['source_updated_at'] is None
    assert row['data_collected_at'] == '2026-10-20T09:00:00+09:00'
    assert database.calls == [('nearby_facilities', {
        'p_latitude': 37.5, 'p_longitude': 127.0,
        'p_facility_type': kind, 'p_radius_m': 250})]


def test_detail_found_and_missing(database):
    facility_id = '00000000-0000-0000-0000-000000000001'
    assert client.get('/api/facilities/' + facility_id).status_code == 404
    database.rows = [{'id': facility_id, 'facility_type': 'aed', 'location': 'private-geometry',
                      'access_hours': [{'weekday': 3}, {'weekday': 1}]}]
    response = client.get('/api/facilities/' + facility_id)
    assert response.status_code == 200
    assert 'location' not in response.json()
    assert response.json()['access_hours'] == [{'weekday': 1}, {'weekday': 3}]
    assert ('id', facility_id) in database.calls


@pytest.mark.parametrize('path', [
    '/api/facilities/nearby?latitude=37.5&longitude=127',
    '/api/facilities/00000000-0000-0000-0000-000000000001'])
def test_database_failure_is_sanitized(database, path):
    database.error = True
    response = client.get(path)
    assert response.status_code == 503
    assert response.json() == {'detail': 'Facility database unavailable'}


def test_missing_configuration_is_503(monkeypatch):
    app.dependency_overrides.clear()
    def unavailable():
        raise ValueError('secret-test-must-not-leak')
    monkeypatch.setattr('app.facilities.create_supabase_client', unavailable)
    response = client.get('/api/facilities/nearby?latitude=37.5&longitude=127')
    assert response.status_code == 503
    assert 'secret-test' not in response.text


@pytest.mark.parametrize('query', ['latitude=91&longitude=127',
    'latitude=37&longitude=181', 'latitude=37&longitude=127&radius_m=0',
    'latitude=37&longitude=127&radius_m=20001'])
def test_invalid_search_rejected(database, query):
    assert client.get('/api/facilities/nearby?' + query).status_code == 422
    assert database.calls == []
