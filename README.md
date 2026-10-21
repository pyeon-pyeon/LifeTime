## backend**

LifeTime 백엔드·DB·보안

AED와 응급의료기관 공공데이터를 수집하고, 주변 시설 조회·시설 상세·보행 경로 비교·예상 도착 시각 기준 AED 이용시간 판단을 제공하는 백엔드다. 시설정보의 비정상 변경 감지·관리자 승인·복구도 핵심 개발 범위에 포함한다.

**작성 기준: 2026-10-21.** 현재는 서버·Supabase 조회 연결과 핵심 로직의 로컬 구현을 마쳤다. 실제 DB의 마지막 확인 건수는 시설·AED·운영시간 모두 **0건**이며, 실데이터 적재와 배포는 미완료다. 이번 문서 정리에서 실DB를 다시 조회하지는 않았다.

## 1. 확정한 8단계와 진행 상태

아래 8단계를 모두 유지한다. `로컬 구현`은 코드와 로컬 테스트가 준비됐다는 뜻이며 실제 Supabase 적용·외부 API 검증·배포 완료를 뜻하지 않는다.


| 순서 | 할 일                                       | 제작한 결과물·확인 사항                                                                          | 현재 상태와 남은 작업                                                                                |
| ------ | --------------------------------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| 1    | AED·응급의료기관 API 활용신청 및 응답 확인 | AED 응답 샘플·파서, 응급의료기관 응답 검증·파서, 실제 샘플 기반 필드 매핑                       | 부분 진행. 현재 PC에는 공공데이터 키가 없어 재호출 미실행. 원래 PC에서 활용신청·키·원본 확인 필요  |
| 2    | FastAPI 프로젝트·Supabase DB 구성          | 실행 가능한 서버, SDK 연결, 기본 스키마·공간 검색 SQL. 실제 두 테이블·통계·주변 검색 함수 확인 | 기본 구성 확인. 승인·복구용 추가 SQL은 실DB 미적용. 실제 역할별 권한 재검증 필요                    |
| 3    | 시설 데이터 수집·저장                      | AED·응급의료기관 수집기, 정규화·사전 검사, 배치 적재·재시도·원본 대조 스크립트                | 미완료. 현재 PC에 전국 원본 없음. 마지막 실제 AED 0건. 원래 PC에서 대상 지역·건수 확인 후 적재 필요 |
| 4    | 주변 검색·시설 상세 API 구현               | Supabase 검색·상세 조회, 종류 필터, 빈 목록·404·DB 오류 처리                                   | 로컬 구현 및 빈 실제 DB 동작 확인. 존재하는 실데이터의 지도 JSON 검증 필요                           |
| 5    | 보행 경로 API 선정·연동                    | 공급자 교체 인터페이스, TMAP 어댑터, 거리·초 단위 변환, 오류 처리·Mock API 테스트               | 로컬 구현. 실제 서비스 운영 조건·인증키·실경로 검증 미완료                                         |
| 6    | AED 이용시간 판단                           | 출발 시각+duration_sec로 도착 시각 계산, 한국시간·요일·야간·24시간 운영 및 3상태 판단          | 로컬 구현·테스트 통과. 실제 운영시간·휴무 정보 연결 필요                                           |
| 7    | 이상 변경 감지·승인·복구 구현             | 좌표·주소·운영시간 변경 검토, 관리자 API, 후보·이력·복구·버전 충돌·중복 요청 처리, 추가 SQL | 로컬 구현·격리 SQL 테스트 통과. 실DB 적용·관리자 계정·독립 세션 동시성 검증 미완료                |
| 8    | 백엔드 배포                                 | 로컬 서버 실행 절차 정리                                                                          | 미완료. 환경 선정, 서버 환경변수·HTTPS·CORS 설정 및 배포 후 점검 필요                              |

불필요한 부가 기능을 정리해도 위 핵심 기능은 삭제·축소하지 않는다. 기능 삭제나 API 계약 변경은 사전 사용자 승인이 필요하다. 작업 지침은 [AGENTS.md](AGENTS.md), 연결 기준은 [integration-contract.md](docs/integration-contract.md)를 따른다.

## 2. 기술 스택과 팀 연결 규칙

- Python 3.12, FastAPI, Pydantic, Uvicorn, pytest
- Supabase Python SDK 기반 REST/RPC 연결, PostgreSQL·PostGIS 공간 검색
- HTTPX 기반 보행 경로 공급자 어댑터
- 시설 종류: `aed`, `emergency_room`
- 좌표: `latitude`, `longitude` / 거리·소요시간: `distance_m`, `duration_sec`
- 날짜·시간: 시간대 포함 ISO 8601, 판단 기준 `Asia/Seoul`
- 누락 정보는 `null`. `0`·휴무·이용 불가로 임의 대체하지 않음
- 일반 사용자는 시설정보 수정 불가. 현재 위치는 기본적으로 DB에 저장하지 않음
- 팀원은 개발용 Mock으로 시작하고 API 완성 후 교체. Mock은 운영 DB에 적재하지 않음

## 3. API와 핵심 처리

### 시설·추천 API


| API                              | 구현한 동작                                                                       |
| ---------------------------------- | ----------------------------------------------------------------------------------- |
| `GET /api/facilities/nearby`     | 위치·시설 종류·반경으로 Supabase 검색. 기존`facilities`, `count` 응답 유지      |
| `GET /api/facilities/{id}`       | 시설 상세와 access_hours 조회. 미존재 404, DB 장애 503                            |
| `POST /api/aeds/recommendations` | 기존 start·departure_at 입력으로 후보 AED의 보행 경로와 도착 시각 기준 상태 비교 |

추천 성공 응답은 사용자가 승인한 `recommendations`, `count` 구조다. 항목은 `facility_id`, `distance_m`, `duration_sec`, `arrival_at`, `availability`를 사용한다. 예시는 [팀 API 계약](docs/integration-contract.md)에 있다.

후보는 반경 3000m 안의 가까운 AED 최대 10개이며 공급자 결과를 소요시간·거리 순으로 비교한다. 주변 검색의 지리적 거리를 보행 거리·시간으로 위장하지 않는다. 실제 경로 키가 없으면 503이며 Mock은 테스트 의존성 주입으로만 사용한다. 타임아웃·요청 제한·공급자 인증 실패·응답 오류를 구분한다.

### 도착 시각 기준 이용시간 판단

출발 시각에 보행 소요시간을 더한 뒤 한국시간으로 판단한다. 운영 시작은 포함하고 종료는 포함하지 않는다. 이전 요일에서 이어지는 야간 운영, 자정·요일 경계, 24시간 운영을 처리한다.

상태는 `available` / `unavailable` / `unknown`이다. 현재 DB에는 공휴일·임시휴무 정보가 없어 정규 운영시간 안이어도 휴무를 확인할 수 없으면 `unknown`이다. 신뢰할 수 있는 달력 연결부를 분리했으며, 달력을 주입한 API 테스트에서 세 상태를 검증했다.

### 이상 변경·관리자 처리

좌표 이동, 주소 변경·누락, 운영시간 변경·삭제·잘못된 시간 범위를 검토한다. 이동 임계값은 DB 설정으로 분리했으며 초기 500m는 운영 기준 확정값이 아니다.

의심 변경은 후보로 보관하고 기존 제공 데이터를 유지한다. 정상 변경은 기존 원자적 적재 함수를 재사용한다. 승인·거절·복구에 관리자 식별자·사유·시각·이력이 남는다. 행 잠금·버전·스냅샷 비교와 요청 ID로 중복 처리 및 충돌을 방지한다. 복구는 이후 정상 변경을 덮어쓰거나 신규 시설을 삭제하지 않는다.


| 관리자 API                                                 | 입력·역할                                                                                      |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| `POST /api/admin/facilities/{facility_id}/changes`         | request_id와 기존 시설 전체 필드·access_hours를 담은 record 제출. 시설 종류·원본 ID 변경 불가 |
| `POST /api/admin/facility-changes/{change_id}/approve`     | request_id·reason으로 승인                                                                     |
| `POST /api/admin/facility-changes/{change_id}/reject`      | request_id·reason으로 거절                                                                     |
| `POST /api/admin/facility-changes/{change_id}/restore`     | request_id·reason으로 이전 상태 복구                                                           |
| `GET /api/admin/facilities/{facility_id}/history?limit=50` | 관리자에게 후보·전후 값·감사 이력 제공                                                        |

Supabase Auth의 `get_user`로 Bearer 토큰을 검증하고 서버 관리 `app_metadata.role=admin`을 확인한다. 사용자 편집 가능한 user_metadata는 신뢰하지 않는다. DB도 해당 관리자의 현재 권한을 확인한다. 인증 우회 키나 공개 관리자 생성 API는 없다. 계정 권한은 신뢰할 수 있는 Supabase 관리 절차로 부여한다. 같은 요청의 재시도에는 같은 UUID, 다른 작업에는 새 UUID를 사용하며 상태 충돌은 409로 처리한다.

## 4. Supabase와 SQL 적용 상태

기본 테이블은 `public.facilities`, `public.facility_access_hours`다. 종류+원본 ID 유일 제약, 운영시간 외래키, 좌표 검사, PostGIS 위치 갱신 트리거·GiST 인덱스가 정의돼 있다. 기본 SQL은 RLS를 활성화하고 anon·authenticated에 SELECT만 부여한다. service_role은 기존 기본 테이블에 직접 쓰기 권한이 있는 서버 자격증명이며 클라이언트에 제공하면 안 된다.


| 순서 | SQL                                                                                                        | 역할·실제 적용 상태                                                            |
| ------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| 1    | [20261020130000_facilities_schema.sql](supabase/migrations/20261020130000_facilities_schema.sql)           | 기본 테이블·RLS·적재/통계 함수. 실제 두 테이블·통계 함수 확인                |
| 2    | [20261020140000_nearby_facilities.sql](supabase/migrations/20261020140000_nearby_facilities.sql)           | 기본 스키마·PostGIS에 의존하는 주변 검색. 실제 읽기 실행 성공                  |
| 3    | [20261021010000_facility_change_review.sql](supabase/migrations/20261021010000_facility_change_review.sql) | 변경 후보·이력·임계값·재시도 기록 및 승인/복구 함수.**운영 Supabase 미적용** |

3번은 `facility_change_requests`, `facility_change_events`, `facility_change_settings`, `facility_import_batches`를 추가한다. 기존 적재 함수를 private 스키마로 이동해 검토 계층 뒤에서 재사용하고 갱신 시각 처리도 보강한다. 기존 public 적재 진입점은 유지된다. 새 적재 CLI는 `stage_facility_batch`를 사용하므로 3번 적용이 필요하다.

SQL은 사전 검토·별도 승인 후 적용한다. 기존 적용 여부를 먼저 확인하고 이미 적용한 파일을 임의로 재실행하지 않는다. PostGIS 설치 스키마와 같은 이름의 기존 함수·정책·인덱스를 비교한다. 테이블 삭제·전체 초기화로 충돌을 해결하지 않는다. 적재 함수는 대상 시설의 운영시간을 교체하므로 데이터 차이와 부작용을 검토한다.

사전 점검은 [preflight_facilities.sql](supabase/preflight_facilities.sql), 기본 적용 후 검증은 [verify_facilities.sql](supabase/verify_facilities.sql), 절차는 [migration-application.md](docs/migration-application.md)를 참고한다. 기존 적용 안내는 기본 1·2번 대상이며 3번 검토·승인·실환경 검증은 추가로 필요하다.

## 5. 실제 검증 결과와 한계

마지막 실DB 기록은 [aed-verification-20261021.md](docs/aed-verification-20261021.md)에 있다. 과거 문서의 전국 수집 건수는 현재 DB 건수가 아니다.


| 환경                         | 마지막 실제 결과                                                                                               | 미검증 항목                              |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Supabase SDK·통계 RPC       | 전체 시설 0건, AED 0건, 운영시간 0건. 주변 검색은 빈 배열 반환                                                 | 적재된 시설의 좌표·운영시간 품질        |
| 실제 DB를 사용하는 로컬 HTTP | health 200, AED·응급실 주변 조회 200 빈 목록, 미존재 상세 404, 잘못된 좌표·시간대 누락 422, 경로 키 누락 503 | 존재하는 시설 상세·실제 보행 결과       |
| Python 자동화 테스트         | **103개 통과, 실패 0개**. 운영시간·추천·관리자 인증 경계·오류·기존 회귀 포함                               | 실제 공급자·관리자 토큰 검증            |
| 격리 SQL 테스트              | **20개 통과, 실패 0개**. 승인·거절·복구·감사·재시도·경쟁 버전 충돌·권한 검증                             | 실제 PostGIS 및 독립 DB 세션의 동시 요청 |

로컬 테스트는 합계 **123개 통과**다. Python의 DB·외부 응답 검증에는 Mock을 사용하며 SQL 테스트는 PostgreSQL WASM에서 공간 저장 보조 함수를 대체한다. 실환경 완료로 보고하지 않는다. Starlette/httpx 사용 중단 예정 경고 1개가 남아 있다.

두 기본 테이블의 RLS 활성화·좌표 불일치 0건은 사용자가 SQL Editor에서 확인한 사항이다. 서버 SDK 조회 성공만으로 일반 사용자 권한까지 검증한 것은 아니다. 실환경 최종 체크리스트는 [AGENTS.md](AGENTS.md)에 유지한다.

## 6. 로컬 실행 — Windows PowerShell

모든 명령은 **저장소 루트** 기준이다. 기존 가상환경이 있으면 생성 단계를 생략한다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

`backend/.env`가 없을 때만 예제를 복사하고 로컬에서 실제 값을 입력한다. 기존 파일을 덮어쓰지 않는다.

```powershell
if (-not (Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --env-file backend\.env --reload --host 127.0.0.1 --port 8000
```

API 문서는 `http://127.0.0.1:8000/docs`, 서버 상태는 `/health`에서 확인한다.


| 환경변수                          | 용도                                                    |
| ----------------------------------- | --------------------------------------------------------- |
| SUPABASE_URL, SUPABASE_SECRET_KEY | SDK 기반 서버 조회·적재·관리 작업                     |
| AED_API_KEY                       | AED 공공데이터 수집                                     |
| EMERGENCY_API_KEY                 | 응급의료기관 수집. 필요하면 로컬 .env에 별도 추가       |
| TMAP_API_KEY                      | 실제 보행 경로 공급자 호출                              |
| DATABASE_URL                      | 선택적인 PostgreSQL 직접 연결 점검. SDK 사용에는 불필요 |

`.env`, 인증키, DB 비밀번호, `.venv`, 대용량 원본은 Git에 포함하지 않는다. 실제 값을 채팅·로그에 출력하지 않는다. 클라이언트는 특정 프로젝트 ref를 검증하므로 대상 프로젝트를 바꾸면 코드의 검증 설정도 검토한다.

## 7. 원래 PC에서 데이터 작업 재개

현재 PC에는 전국 원본이 없고 AED 10건 샘플만 있다. 샘플을 운영 데이터로 적재하지 않았다. **다음 적재 작업은 원본이 있는 기존 PC에서 이어간다.**

1. 기존 PC의 사용자 변경을 보존한 상태에서 코드를 가져오고 로컬 `.env`와 원본을 확인한다.
2. `backend/AED/aed_nationwide.json`, 필요 시 `backend/medical/medical_nationwide.json`을 확인한다. 없으면 공공데이터 활용신청·키 설정 후 기존 수집기를 사용한다.
3. 대상 지역·출처·기준일·수집 시각·좌표·필수값·중복·운영시간을 검사한다. 원천 갱신일을 모르면 null로 유지한다.
4. 변경 검토 SQL의 별도 승인·적용·권한 검증 후 기존 원본 ID와 비교한다.
5. 적재 대상·신규·갱신·보류 예상 건수를 먼저 확인한다. 덮어쓰기 위험이 있으면 승인 전 실행하지 않는다.
6. 적재 후 SQL·통계·원본 대조와 실제 시설의 주변·상세·추천 API를 검증한다.

연결·사전 검사 명령이다. 마지막 원본 대조는 실제 적재 후 실행한다.

```powershell
.\.venv\Scripts\python.exe backend/scripts/check_facilities_schema.py
.\.venv\Scripts\python.exe backend/scripts/import_facilities.py --dry-run
# 실제 적재·관리자 보류 처리 후:
.\.venv\Scripts\python.exe backend/scripts/verify_aed_import.py
```

실제 적재 명령과 주의사항은 [database-import.md](docs/database-import.md), 원본 매핑은 [field-mapping.md](docs/field-mapping.md)를 참고한다. AED만 기본 적재하며 응급의료기관은 `--medical-json`을 명시해야 한다. 신규·갱신·보류·동일 건수를 구분하고 실패 또는 검토 대기가 있으면 적재 완료로 보고하지 않는다.

## 8. 테스트 재실행

루트 가상환경을 사용하는 Python 테스트:

```powershell
Push-Location backend
..\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
```

격리 SQL 테스트에는 Node.js와 아래 개발용 패키지가 필요하다. 백엔드 실행 자체에는 Node.js가 필요 없다. 테스트는 `.env`를 읽거나 Supabase에 연결하지 않는다.

```powershell
npm.cmd install --prefix .venv/sql-check @electric-sql/pglite@0.5.10
node --test backend/tests/sql/review.test.mjs
```

핵심 구현은 `backend/app/`의 `availability.py`, `walking.py`, `recommendations.py`, `change_detection.py`, `admin.py`에 있다. 추가 테스트는 `backend/tests/test_core_features.py`, `backend/tests/sql/review.test.mjs`에 있다.

## 9. 남은 실환경 작업과 인수인계

우선순위는 기존 PC의 원본·키 확인 → 변경 검토 SQL 승인·적용 → 데이터 검사·적재 → 실데이터 조회 검증 → 경로 키·휴무 정보 연결 → 실제 관리자·동시성 검증 → 배포다.

배포에는 실행 환경 선정, 서버 Secret 환경변수, HTTPS, 프론트엔드 허용 CORS, 장애 응답·권한·실제 API 점검이 남아 있다. 로컬 서버 실행과 배포 완료를 구분한다.

코드와 문서는 아직 커밋·푸시하지 않았다. 다른 PC에서 이어가기 전 `git status`로 변경을 검토하고 코드·SQL·문서를 커밋·푸시한 뒤 가져온다. 비밀값·가상환경·대용량 데이터는 전송 대상에서 제외한다. 이후 커밋·배포하면 이 문서의 상태와 검증 일자도 갱신한다.
