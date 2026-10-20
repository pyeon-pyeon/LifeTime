# Supabase 실행 기록 — 2026-10-20

## 현재 결과

실제 Supabase에는 접속하지 못했다. `backend/.env`, 루트 `.env` 및 프로세스 환경의 `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, `AED_API_KEY`가 모두 없다. 컴퓨터 사용 도구의 브라우저 목록도 빈 목록이어서 SQL Editor 세션에 접근할 수 없었다. 비밀값은 출력하지 않았다.

| 단계 | 상태 | 작업 내용 | 검증 결과 |
| --- | --- | --- | --- |
| DB 스키마 확인 | 로컬 완료 | 기존 facilities, facility_access_hours, RLS, RPC 분석 | 실제 DB 객체와 비교는 미확인 |
| Supabase 테이블 생성 | 미확인 | 기존 마이그레이션 사용, 트랜잭션 보강 | 적용하지 않음, 실제 테이블명 조회 결과 없음 |
| AED 데이터 적재 | 미확인 | 적재 전 전체 검증 추가, 기존 UPSERT 유지 | 이번 작업 DB 쓰기 0건, 기존 DB 총건수는 모름 |
| 데이터 검증 | 로컬 완료 | verify_facilities.sql 준비 | 실제 COUNT, 누락, 중복, 주요 값 모두 미확인 |
| API 연결 확인 | 로컬 완료 | 실제 Supabase 조회 코드, Mock 테스트, 로컬 HTTP 실행 | 실제 Supabase 데이터 응답 미확인 |

## 실제 실행 근거

- `git pull --ff-only origin main`: Already up to date. 기존 작업 트리는 깨끗했다. AGENTS.md는 저장소 및 확인한 상위 경로에서 발견되지 않았다.
- `python backend/scripts/check_supabase_api.py`: `SupabaseConfigurationError`, 종료 코드 1. 네트워크 요청 전에 설정 검증에서 중단.
- `python backend/scripts/check_database_connection.py`: DATABASE_URL 없음, 종료 코드 1. SQL 실행 없음.
- `python backend/scripts/import_facilities.py --dry-run`: `backend/AED/aed_nationwide.json` 없음, 종료 코드 1. DB 쓰기 없음.
- `python -m pytest tests -q` (backend): 47 passed. Supabase 연동 응답 테스트는 FakeDatabase를 사용한 Mock 테스트이며 실제 DB 검증이 아니다. 임시 폴더 권한으로 처음 5개 setup 오류가 발생했으나 권한을 허용한 동일 테스트 재실행에서 모두 통과했다. Starlette/httpx 사용 중단 예정 경고 1개가 남는다.
- 실제 로컬 Uvicorn 프로세스 `127.0.0.1:18765`에 HTTP 요청 후 프로세스 종료: `/health` 200, 주변 조회 503 `Facility database unavailable`, 상세 조회 503 같은 메시지, 추천 503 `Walking route provider not configured`. 실제 DB 데이터가 반환된 것은 아니다.
- Python compileall 통과. SQL은 실제 PostgreSQL/PostGIS에서 실행되지 않아 실행 검증 미완료.
- `python -m scripts.check_live_facilities` (backend): `SupabaseConfigurationError`, 종료 코드 1. Mock 없이 실제 연결을 요구하며 설정 검증에서 중단했다.

## 스키마와 안전성

대상 테이블은 `public.facilities`와 `public.facility_access_hours`다. 시설 UUID 기본키, 종류+원본 ID 유일 제약, 운영시간 복합 기본키와 시설 외래키, 좌표 범위 검사, GiST 공간 인덱스가 정의돼 있다. `anon`, `authenticated`는 두 테이블 SELECT만 허용하며 쓰기 권한은 철회한다. 적재/통계/주변 검색 RPC는 서버 역할에만 허용한다. 사용자 위치 저장 테이블이나 쓰기 API는 추가하지 않았다.

기존 데이터 삭제나 초기화는 하지 않았다. 기존 적재 RPC는 시설별 운영시간을 같은 트랜잭션에서 교체한다. 기본 마이그레이션에 BEGIN/COMMIT을 추가하고, 빈 DB에서 없는 테이블을 regclass 상수로 해석하지 않도록 수정했다. 추가 마이그레이션은 조회 함수만 생성한다. 기존 테이블이 있으면 database-schema.md의 열·제약·정책·인덱스 사전 점검을 먼저 실행해야 한다. PostGIS가 extensions 이외 스키마에 설치돼 있으면 현재 SQL의 스키마 수식과 비교 검토가 필요하다.

## 실제 데이터 확보

전국 데이터 파일은 없고 체크인된 AED JSON은 10건 샘플이다. 샘플을 운영 DB에 적재하지 않았다. 원본 레코드 갱신 시점은 확인할 수 없어 `source_updated_at=null`을 유지한다. 수집기는 수집 시각을 시간대 포함 ISO 8601로 기록한다.

[공공데이터포털의 국립중앙의료원 AED 조회 서비스](https://www.data.go.kr/data/15000652/openapi.do)에서 활용 신청 후 인증키를 발급받아 `backend/.env`의 `AED_API_KEY`에 설정한다. 기존 수집기는 FullData 다운로드 기능인 `getAedFullDown`을 호출한다. 이번 실행에서는 인증키가 없어 실제 공공 API 수집을 하지 않았다.

## 사용자 준비 및 다음 실행 순서

모든 PowerShell 명령은 저장소 루트 기준이다. 비밀값은 채팅이나 Git에 넣지 않는다.

1. `Copy-Item backend/.env.example backend/.env` (기존 파일이 없는 경우에만). `SUPABASE_URL`, 서버 전용 `SUPABASE_SECRET_KEY`, 필요한 경우 `AED_API_KEY`를 로컬 파일에 설정한다. 현재 클라이언트는 프로젝트 ref `qjjllzqhljuivburjrqd`만 허용한다. 다른 프로젝트라면 먼저 목표 프로젝트를 확인하고 검증 설정을 수정한다. PostgreSQL 비밀번호는 Secret API Key와 별개이며 SQL Editor 사용 시 DATABASE_URL은 필요 없다.
2. Supabase SQL Editor에서 docs/database-schema.md의 preflight SQL로 프로젝트·기존 객체·PostGIS를 확인한다.
3. `supabase/migrations/20261020130000_facilities_schema.sql` 전체를 실행한 후 `20261020140000_nearby_facilities.sql`을 실행한다. 현재 작업에서 사용자가 실제 적용을 요청했지만 연결 정보가 없어 실행하지 못했다.
4. 전국 JSON을 `backend/AED/aed_nationwide.json`에 복원하거나 다음 명령으로 실제 공공데이터를 수집한다.

```powershell
.\.venv\Scripts\python.exe backend/AED/collect_aed_nationwide.py
.\.venv\Scripts\python.exe backend/scripts/check_supabase_api.py
.\.venv\Scripts\python.exe backend/scripts/import_facilities.py --dry-run
.\.venv\Scripts\python.exe backend/scripts/import_facilities.py --batch-size 500
.\.venv\Scripts\python.exe backend/scripts/verify_aed_import.py
```

5. SQL Editor에서 `supabase/verify_facilities.sql` 전체 실행 후 실제 결과를 이 문서에 추가한다. 핵심 SQL은 아래와 같다. **현재 이 SQL들의 실제 실행 결과는 없다.**

```sql
SELECT tablename FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours');
SELECT COUNT(*) AS aed_count
FROM public.facilities WHERE facility_type = 'aed';
```

검증 파일은 위도/경도 각각의 누락, 세계 좌표 범위 오류, 한국 범위 밖 검토 대상, 종류+원본 ID 중복, 실제 주요 필드, 양쪽 테이블의 역할별 권한도 조회한다. 한국 범위 밖 표시는 검토 대상이며 자동 삭제하지 않는다.

6. 실제 DB를 사용하는 API 검증 스크립트를 실행한다. 실제 AED 좌표로 100m 검색 및 상세 조회를 확인한다. REST exact count도 출력하지만 SQL Editor의 COUNT 실행을 대체하지 않는다.

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m scripts.check_live_facilities
Pop-Location
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

시설 조회는 빈 목록 200, 상세 미존재 404, DB 장애 503을 사용한다. 잘못된 좌표/종류/반경은 422다. 경로 추천은 도보 공급자가 없으므로 기존 503을 유지한다. `duration_sec`를 임의로 계산하거나 응급실 수용 가능 정보를 만들어 반환하지 않는다. 프론트엔드 소스는 이 저장소에 없어 실제 화면 연동은 확인하지 못했다.

자동 커밋/푸시하지 않았다. `.venv`와 비밀값, 적재 오류 로그는 Git 제외 대상이다.
