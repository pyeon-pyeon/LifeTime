"""All fixtures are synthetic; these tests never contact Supabase or a route service."""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from app.availability import evaluate_arrival
from app.change_detection import detect_changes, movement_m
from app.facilities import get_facility_client
from app.main import app
from app.walking import TmapWalkingProvider, WalkingRoute, RouteError, get_walking_provider
from app.recommendations import get_closure_calendar

FID = '00000000-0000-0000-0000-000000000001'
ACTOR = '00000000-0000-0000-0000-000000000002'
REQUEST = '00000000-0000-0000-0000-000000000003'


def hours(opens='09:00', closes='18:00', overnight=False, all_day=False):
    return [dict(weekday=d, opens_at=opens, closes_at=closes,
                 ends_next_day=overnight, is_24_hours=all_day) for d in range(1, 8)]


def decision(departure, duration=0, schedule=None, closure=False):
    return evaluate_arrival(datetime.fromisoformat(departure), duration,
                            hours() if schedule is None else schedule, closure=closure)


@pytest.mark.parametrize('departure,status', [
    ('2026-10-19T08:59:59+09:00','unavailable'),
    ('2026-10-19T09:00:00+09:00','available'),
    ('2026-10-19T17:59:59+09:00','available'),
    ('2026-10-19T18:00:00+09:00','unavailable'),
    ('2026-10-24T12:00:00+09:00','available'),
    ('2026-10-25T12:00:00+09:00','available'),
    ('2026-10-19T00:00:00Z','available'),
])
def test_weekdays_weekends_boundaries_and_timezone(departure, status):
    assert decision(departure).availability == status


def test_arrival_not_departure_and_date_boundary():
    result = decision('2026-10-19T17:59:00+09:00', 120)
    assert result.availability == 'unavailable'
    result = decision('2026-10-25T23:59:00+09:00', 120, hours('22:00','02:00',True))
    assert result.arrival_at.isoformat() == '2026-10-26T00:01:00+09:00'
    assert result.availability == 'available'
    assert decision('2026-10-26T02:00:00+09:00', schedule=hours('22:00','02:00',True)).availability == 'unavailable'


def test_24_hours_missing_partial_and_calendar():
    assert decision('2026-10-20T23:59:00+09:00', schedule=hours('00:00','00:00',True,True)).availability == 'available'
    assert decision('2026-10-20T12:00:00+09:00', schedule=[]).availability == 'unknown'
    assert decision('2026-10-20T12:00:00+09:00', schedule=hours()[2:]).availability == 'unknown'
    assert decision('2026-10-20T12:00:00+09:00', closure=None).availability == 'unknown'
    assert decision('2026-10-20T12:00:00+09:00', closure=True).availability == 'unavailable'


@pytest.mark.parametrize('schedule', [hours('09:00','09:00'), hours('09:00','18:00',True),
                                     hours('18:00','09:00'), hours('01:00','00:00',True,True)])
def test_invalid_hours_unknown(schedule):
    assert decision('2026-10-20T12:00:00+09:00', schedule=schedule).availability == 'unknown'


@pytest.mark.parametrize('duration', [-1, float('nan'), float('inf'), True, 8*86400])
def test_bad_duration_rejected(duration):
    with pytest.raises(ValueError):
        decision('2026-10-20T12:00:00+09:00', duration)


def test_missing_timezone_rejected():
    with pytest.raises(ValueError):
        decision('2026-10-20T12:00:00')


def facility():
    return dict(id=FID, facility_type='aed', source_id='SYNTHETIC',name='Fixture',address='Fixture address',
                latitude=37.5,longitude=127.0,schedule_status='known',access_hours=hours())


def test_detection_normal_move_hours_address_missing():
    old=facility(); new=deepcopy(old); new['name']='Updated fixture'
    assert detect_changes(old,new)==[]
    new['latitude']=37.6
    assert movement_m(old,new)>10000
    assert 'coordinate_movement' in detect_changes(old,new)
    assert 'coordinate_movement' not in detect_changes(old,new,threshold_m=20000)
    new=deepcopy(old); new['access_hours']=[]
    assert 'hours_changed' in detect_changes(old,new)
    new=deepcopy(old); new['access_hours']=hours('00:00','00:00')
    assert 'invalid_hours' in detect_changes(old,new)
    new=deepcopy(old); new['address']=None; new['longitude']=None
    assert {'missing_address','missing_longitude','address_changed'} <= set(detect_changes(old,new))


START = {'latitude':37.5,'longitude':127.0}
DEPARTURE = datetime.fromisoformat('2026-10-20T12:00:00+09:00')


def test_tmap_adapter_units_axes_and_no_key_in_url():
    def handler(request):
        import json
        body=json.loads(request.content)
        assert body['startX']==127 and body['startY']==37.5
        assert 'appKey' in request.headers and 'unit-test-only' not in str(request.url)
        return httpx.Response(200,json={'features':[{'properties':{'totalDistance':1234,'totalTime':900}}]})
    route=TmapWalkingProvider('unit-test-only',httpx.MockTransport(handler)).route(START,START,DEPARTURE)
    assert route == WalkingRoute(1234,900)


@pytest.mark.parametrize('status,category', [(401,'authentication_failed'),(403,'authentication_failed'),
    (429,'rate_limited'),(500,'upstream_error')])
def test_provider_http_errors(status,category):
    transport=httpx.MockTransport(lambda request:httpx.Response(status))
    with pytest.raises(RouteError) as caught:
        TmapWalkingProvider('fixture-key',transport).route(START,START,DEPARTURE)
    assert caught.value.category==category


@pytest.mark.parametrize('error,category', [(httpx.ReadTimeout('secret'),'timeout'),
                                         (httpx.ConnectError('secret'),'network_error')])
def test_provider_network_errors(error,category):
    def handler(request): raise error
    with pytest.raises(RouteError) as caught:
        TmapWalkingProvider('fixture-key',httpx.MockTransport(handler)).route(START,START,DEPARTURE)
    assert caught.value.category==category
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('payload', [{},{'features':[]},
    {'features':[{'properties':{'totalDistance':-1,'totalTime':10}}]},
    {'features':[{'properties':{'totalDistance':10,'totalTime':'10'}}]}])
def test_bad_provider_payload(payload):
    with pytest.raises(RouteError) as caught:
        TmapWalkingProvider('fixture-key',httpx.MockTransport(lambda request:httpx.Response(200,json=payload))).route(START,START,DEPARTURE)
    assert caught.value.category=='invalid_response'


def test_missing_key_and_bad_coordinates():
    with pytest.raises(RouteError): TmapWalkingProvider('')
    with pytest.raises(RouteError) as caught:
        TmapWalkingProvider('fixture-key').route({'latitude':127,'longitude':37},START,DEPARTURE)
    assert caught.value.category=='invalid_coordinates'


class Database:
    def __init__(self, role='admin', auth_error=False, rpc_error=None):
        self.calls=[]; self.role=role; self.auth_error=auth_error; self.rpc_error=rpc_error
        self.auth=SimpleNamespace(get_user=self.get_user)
        self.row=facility()

    def get_user(self, token):
        if self.auth_error: raise RuntimeError('sensitive-auth-error')
        return SimpleNamespace(user=SimpleNamespace(id=ACTOR,app_metadata={'role':self.role},user_metadata={'role':'admin'}))

    def rpc(self, name, params):
        self.calls.append((name,params)); self.name=name; return self

    def table(self, table): self.name=table; return self
    def select(self, fields): return self
    def eq(self, name, value): return self
    def limit(self, value): return self

    def execute(self):
        if self.rpc_error: raise self.rpc_error
        if self.name=='nearby_facilities': return SimpleNamespace(data=[self.row])
        if self.name=='facilities': return SimpleNamespace(data=[self.row])
        if self.name=='facility_change_history': return SimpleNamespace(data=[])
        return SimpleNamespace(data={'id':FID,'status':'pending'})


class MockWalkingProvider:
    def route(self, start, destination, departure_at): return WalkingRoute(120,100)


@pytest.fixture
def api():
    db=Database()
    app.dependency_overrides[get_facility_client]=lambda:db
    app.dependency_overrides[get_walking_provider]=lambda:MockWalkingProvider()
    with TestClient(app) as client: yield client,db
    app.dependency_overrides.clear()


def test_recommendation_api_approved_contract(api):
    client,db=api
    response=client.post('/api/aeds/recommendations',json={'start':START,'departure_at':DEPARTURE.isoformat()})
    assert response.status_code==200
    assert response.json()=={'recommendations':[{'facility_id':FID,'distance_m':120,'duration_sec':100,
        'arrival_at':'2026-10-20T12:01:40+09:00','availability':'unknown'}],'count':1}
    assert db.calls[0][1]['p_facility_type']=='aed'


def test_recommendation_service_known_calendar(api):
    from app.main import RecommendationRequest
    from app.recommendations import recommend
    _,db=api
    request=RecommendationRequest(start=START,departure_at=DEPARTURE)
    result=recommend(db,MockWalkingProvider(),request,calendar=lambda fid,day:False)
    assert result['recommendations'][0]['availability']=='available'


@pytest.mark.parametrize('closure,status', [(False,'available'),(True,'unavailable'),(None,'unknown')])
def test_recommendation_api_trusted_calendar(api,closure,status):
    app.dependency_overrides[get_closure_calendar]=lambda:lambda fid,day:closure
    response=api[0].post('/api/aeds/recommendations',json={'start':START,'departure_at':DEPARTURE.isoformat()})
    assert response.status_code==200
    assert response.json()['recommendations'][0]['availability']==status


def test_inconsistent_schedule_status_unknown():
    assert evaluate_arrival(DEPARTURE,0,hours(),closure=False,schedule_status='unknown').availability=='unknown'


def test_guarded_import_returns_separate_counts_and_stable_retry_id(monkeypatch):
    from scripts.import_facilities import upsert_batch, normalize_record
    monkeypatch.setattr('scripts.import_facilities.time_module.sleep',lambda _:None)
    class RetryingDatabase:
        def __init__(self):self.calls=[]
        def rpc(self,name,params):
            self.calls.append((name,dict(params)))
            return self
        def execute(self):
            if len(self.calls)==1:raise RuntimeError('Transient transport failure')
            return SimpleNamespace(data={'inserted':1,'updated':0,'held':0,'unchanged':0})
    db=RetryingDatabase()
    result=upsert_batch(db,[normalize_record({'facility_type':'aed','source_id':'FIXTURE'},'aed')],detailed=True)
    assert result['inserted']==1
    assert db.calls[0][0]=='stage_facility_batch'
    assert db.calls[0][1]['p_request_id']==db.calls[1][1]['p_request_id']


@pytest.mark.parametrize('category,status', [('timeout',504),('rate_limited',503),('invalid_response',502)])
def test_recommendation_error_mapping(api,category,status):
    class FailedProvider:
        def route(self,*args): raise RouteError(category)
    app.dependency_overrides[get_walking_provider]=lambda:FailedProvider()
    response=api[0].post('/api/aeds/recommendations',json={'start':START,'departure_at':DEPARTURE.isoformat()})
    assert response.status_code==status


HEADERS={'Authorization':'Bearer synthetic-token'}
BODY={'request_id':REQUEST,'reason':'fixture review'}


@pytest.mark.parametrize('action', ['approve','reject','restore'])
def test_admin_decisions_call_atomic_rpc(api,action):
    client,db=api
    response=client.post(f'/api/admin/facility-changes/{FID}/{action}',headers=HEADERS,json=BODY)
    assert response.status_code==200
    name,params=db.calls[-1]
    assert name=='decide_facility_change'
    assert params['p_actor_id']==ACTOR and params['p_action']==action


def test_admin_propose_and_history(api):
    client,db=api
    record=facility(); record.pop('id')
    response=client.post(f'/api/admin/facilities/{FID}/changes',headers=HEADERS,
                         json={'request_id':REQUEST,'record':record})
    assert response.status_code==200
    assert db.calls[-1][0]=='propose_facility_change'
    assert client.get(f'/api/admin/facilities/{FID}/history',headers=HEADERS).status_code==200


@pytest.mark.parametrize('action', ['approve','reject','restore'])
def test_nonadmin_cannot_decide_even_with_spoofed_user_metadata(api,action):
    client,db=api; db.role='member'
    response=client.post(f'/api/admin/facility-changes/{FID}/{action}',headers=HEADERS,json=BODY)
    assert response.status_code==403 and not db.calls


def test_missing_invalid_auth_and_history_permission(api):
    client,db=api
    assert client.post(f'/api/admin/facility-changes/{FID}/approve',json=BODY).status_code==401
    db.auth_error=True
    assert client.post(f'/api/admin/facility-changes/{FID}/approve',headers=HEADERS,json=BODY).status_code==401
    db.auth_error=False;db.role='member'
    assert client.get(f'/api/admin/facilities/{FID}/history',headers=HEADERS).status_code==403
    assert not db.calls


@pytest.mark.parametrize('code,status', [('40001',409),('23505',409),('42501',403),
    ('P0002',404),('22023',422),('PGRST202',503)])
def test_admin_rpc_errors_are_sanitized(api,code,status):
    class Error(Exception): pass
    error=Error('secret-should-not-leak');error.code=code
    api[1].rpc_error=error
    response=api[0].post(f'/api/admin/facility-changes/{FID}/approve',headers=HEADERS,json=BODY)
    assert response.status_code==status and 'secret' not in response.text
