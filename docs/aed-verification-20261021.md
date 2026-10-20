# AED 적재 전 실제 DB·API 검증 — 2026-10-21

## 결론

Supabase 실제 조회 성공. facilities, facility_access_hours는 모두 비어 있으며 AED도 실제 0건이다. 전국 원본 `backend/AED/aed_nationwide.json`이 없고 `AED_API_KEY`도 설정되지 않았다. 사용자 지시에 따라 원본 누락 상태에서 적재를 중단했다. 저장소의 AED 10건 샘플은 운영 DB에 넣지 않았다.

이번 작업의 신규 삽입 0건, 갱신 0건. 적재 호출 자체를 하지 않아 실패/건너뜀 레코드 집계는 미실행이다. 원본 전체 건수와 적재 대상 건수도 아직 산정하지 않았다. 스키마 변경, 함수 생성·수정, 데이터 삭제를 하지 않았다.

## 준비 확인

- AGENTS.md, README.md, 팀 연결 규칙, 기존 적재/검증/수집 스크립트 확인.
- 기존 미커밋 변경 사항 보존. 원격 main fetch 후 HEAD...origin/main 차이 0/0. 병합·커밋·푸시하지 않음.
- backend/.env의 Supabase URL·Secret Key 설정 확인. 값은 출력하지 않음. 코드의 허용 프로젝트와 일치.
- DATABASE_URL 미설정. 따라서 PostgreSQL 직접 접속이나 카탈로그 SQL 실행은 하지 않음.
- 서비스 역할 SDK의 조회 성공은 일반 사용자의 RLS/권한 검증을 대체하지 않는다.

## 실제 DB 조회 결과

SDK exact count 및 읽기 RPC를 사용했다. 아래 결과는 Mock이 아니다.

| 조회 | 실제 결과 |
| --- | --- |
| facilities 전체 exact count | 0 |
| facilities의 facility_type=aed exact count | 0 |
| facility_access_hours 전체 exact count | 0 |
| get_aed_import_stats 실행 | 성공 |
| nearby_facilities(37.5665, 126.9780, aed, 3000) 실행 | 성공, 빈 배열 |
| API 명세의 upsert_facility_batch | 존재 확인, 호출하지 않음 |
| API 명세의 get_aed_import_stats / nearby_facilities | 모두 존재 |

실제 통계 RPC 응답:

```json
{
  "aed_count": 0,
  "access_hours_count": 0,
  "emergency_room_count": 0,
  "schedule_status_counts": {},
  "distinct_source_id_count": 0,
  "missing_coordinate_count": 0,
  "out_of_range_coordinate_count": 0
}
```

AED count와 distinct source ID count가 모두 0이므로 중복 초과 행도 0이다. 데이터가 비어 있어 좌표 누락·범위 오류 0건은 실제 좌표 품질 검증 완료를 뜻하지 않는다. 운영시간도 0행이므로 한국시간 기준 운영 여부와 야간 운영은 실데이터 미검증이다.

## 검증 SQL과 실행 방식 구분

이번 작업에서는 SQL Editor에 SQL을 붙여 실행하지 않았다. 위 실제 결과는 SDK count 및 DB 안에서 SQL을 실행하는 기존 get_aed_import_stats RPC에서 얻었다. 다음은 같은 항목을 SQL Editor에서 재확인할 읽기 SQL이며, 이번 작업에서 아래 문자열을 직접 SQL로 실행한 것은 아니다.

```sql
SELECT count(*) AS facilities_total FROM public.facilities;
SELECT count(*) AS aed_count FROM public.facilities WHERE facility_type = 'aed';
SELECT count(*) AS access_hours_total FROM public.facility_access_hours;
SELECT public.get_aed_import_stats();
SELECT public.nearby_facilities(37.5665, 126.9780, 'aed', 3000);
SELECT source_id, count(*) FROM public.facilities
WHERE facility_type = 'aed' GROUP BY source_id HAVING count(*) > 1;
```

RLS 정책·함수 권한 등 전체 검증은 `supabase/verify_facilities.sql`을 사용한다. 두 테이블 RLS 활성화 및 좌표/location 불일치 0건은 사용자가 전달한 이전 확인 사항이다. 이번에는 해당 카탈로그를 직접 재조회하지 못했으며 anon/authenticated의 실효 권한도 미확인이다. 적재 RPC의 쓰기 권한을 확인하려고 빈 배치를 호출하는 작업도 하지 않았다.

## 실제 HTTP API 테스트

로컬 Uvicorn을 실행해 HTTP 요청을 보냈으며 종료 후 프로세스를 정리했다. Supabase 조회는 실제 인증정보를 사용했고 dependency override나 Mock은 사용하지 않았다.

| 요청 | 상태 | 실제 응답/판정 |
| --- | --- | --- |
| GET /health | 200 | status=ok |
| GET /api/facilities/nearby (aed) | 200 | facilities=[], count=0 |
| GET /api/facilities/nearby (emergency_room) | 200 | facilities=[], count=0 |
| GET /api/facilities/00000000-0000-0000-0000-000000000001 | 404 | Facility not found |
| GET /api/facilities/nearby (latitude=127) | 422 | 위경도 범위 오류 거부 |
| POST /api/aeds/recommendations (한국시간 offset 포함) | 503 | Walking route provider not configured |
| POST /api/aeds/recommendations (offset 없음) | 422 | 시간대 누락 거부 |

상태/응답 검사 6개 통과, health 별도 성공. 실제 AED가 없어 존재하는 시설 상세, 실제 거리 distance_m, 반환 시각 및 운영시간 판정은 미검증이다. 경로 추천의 duration_sec 및 실제 경로 비교도 미검증이다.

별도 로컬 자동화 테스트 `python -m pytest tests -q`: **47 passed**, Starlette/httpx 사용 중단 예정 경고 1개. 여기 포함된 DB 장애·시설 응답 테스트는 Mock 기반이며 실제 DB 검증과 구분한다.

## 출처와 다음 단계

[국립중앙의료원_전국 자동심장충격기(AED) 정보 조회 서비스](https://www.data.go.kr/data/15000652/openapi.do)의 공공데이터포털 페이지에서 활용 신청 후 인증키를 확보한다. 기존 수집기는 서비스의 FullData 다운로드 `getAedFullDown`을 사용한다. 이번에는 실제 공공데이터를 수집하지 않았으므로 사용한 데이터의 기준일·갱신일은 미확인이다. 포털 페이지 수정일을 개별 AED 갱신일로 사용하지 않는다.

1. 기존 전국 JSON을 `backend/AED/aed_nationwide.json`에 복원하거나, 공공데이터 API 활용 신청 후 `backend/.env`에 `AED_API_KEY`를 설정한다. 비밀값은 채팅·Git에 넣지 않는다.
2. 필요하면 저장소 루트에서 `.\.venv\Scripts\python.exe backend/AED/collect_aed_nationwide.py`로 수집한다. 원본은 유지한다.
3. 원본 확보 후 필드·한국 좌표 범위·중복·수집 시각·운영시간 정합성을 검증하고 실제 DB와 source_id를 비교한다.
4. `(facility_type, source_id)` UPSERT는 같은 시설을 갱신한다. 적재 RPC는 입력한 시설의 운영시간 전체를 삭제 후 재삽입하므로, 부분 운영시간 입력도 기존 정보를 지울 수 있다. 원본과 기존 행의 차이를 보고하고 기존 데이터 덮어쓰기 위험이 있으면 승인 전 호출하지 않는다.
5. 실제 입력 건수와 신규/갱신/실패를 구분해 적재하고, 위 SQL·기존 verify_aed_import.py·실데이터 API 테스트를 다시 실행한다. 이번 작업에서는 적재를 시작하지 않았다.

이번 단계에서 새로 만든 파일은 이 보고서뿐이다. 기존 코드·SQL·인증정보는 변경하지 않았다.
