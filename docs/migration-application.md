# Supabase 마이그레이션 적용 순서

## 적용 상태 — 2026-10-21

이번 작업은 로컬 검토·검증 파일 준비 단계다. 실제 마이그레이션은 실행하지 않았다. 마지막 실제 SDK 조회에서는 두 테이블이 스키마 캐시에 없다는 404가 반환됐다. AED 건수는 미확인이며 0건으로 확인된 것이 아니다.

로컬 `backend/.env`의 URL이 코드가 허용하는 프로젝트 ref와 일치함을 값 출력 없이 확인했다. SQL Editor는 별도 세션이므로 Dashboard의 프로젝트 ref가 **`qjjllzqhljuivburjrqd`**인지 직접 대조해야 한다. 프로젝트 이름이나 `current_database() = postgres`만으로는 같은 프로젝트임을 증명할 수 없다. Secret Key나 전체 접속 URL은 공유할 필요가 없다.

## SQL Editor에서 사용자가 실행할 순서

1. 위 프로젝트 ref를 대조한다.
2. `supabase/preflight_facilities.sql` 전체 실행. 테이블이 있으면 열·제약·인덱스·트리거·정책·권한·같은 이름 함수의 정의를 기존 마이그레이션과 비교하고, 파일 하단의 별도 건수 쿼리도 실행해 결과를 보관한다. 테이블이 없으면 건수 쿼리는 실행하지 않는다.
3. 사전 점검이 적합하면 `supabase/migrations/20261020130000_facilities_schema.sql` 전체를 실행한다. 부분 선택 실행하지 않는다. 성공한 경우에만 다음 파일로 넘어간다.
4. `supabase/migrations/20261020140000_nearby_facilities.sql` 전체 실행.
5. 두 파일이 성공하면 `supabase/verify_facilities.sql` 실행. 실제 결과를 보관한다.
6. 적용 완료를 알려주면 아래 SDK 읽기 전용 재조회로 검증한다. AED 적재는 이 단계에 포함하지 않는다.

## 실행 순서와 의존성

| 순서 | 파일 | 역할·의존성 |
| --- | --- | --- |
| 1 | `20261020130000_facilities_schema.sql` | extensions 스키마의 PostGIS, 두 테이블, PK·FK·좌표/종류 제약·인덱스·트리거·RLS·권한·적재/통계 함수 생성 |
| 2 | `20261020140000_nearby_facilities.sql` | 1번의 facilities.location 및 PostGIS에 의존하는 읽기 전용 주변 검색 함수 생성 |

기존 두 마이그레이션 파일은 이번 검토에서 대체하거나 수정하지 않았다.

## 적용 전 위험 사항

- 두 파일은 각각 BEGIN/COMMIT 트랜잭션이다. 1번 성공 후 2번 실패 시 1번은 남는다. 오류 시 테이블 삭제·초기화로 복구하지 말고 원인을 검토한다.
- 마이그레이션 실행 자체에는 시설 INSERT/UPDATE/DELETE/TRUNCATE/DROP TABLE이 없다. 다만 생성하는 적재 함수 본문에는 시설 UPSERT와 운영시간 DELETE/재삽입이 있으므로, 이번 단계에서는 **함수를 정의만 하고 호출하지 않는다**.
- 기존 함수는 CREATE OR REPLACE로 바뀐다. 다른 시스템에서 사용하는 같은 이름 함수가 있다면 정의와 반환형을 먼저 비교한다. 반환형 충돌을 DROP으로 해결하지 않는다.
- 테이블/인덱스 생성과 ALTER TABLE, 권한 변경은 잠금을 유발할 수 있다. 기존 운영 트래픽이 있으면 실행 시간을 조정한다.
- PostGIS가 이미 설치돼 있다면 설치 스키마는 `extensions`여야 한다. 다른 스키마라면 CREATE EXTENSION IF NOT EXISTS로 이동되지 않으며 현재 SQL은 실패할 수 있으므로 중단하고 검토한다.
- 기존 테이블 검사에는 한계가 있다. 모든 기존 PK·FK·CHECK·인덱스 정의가 자동 검증되는 것은 아니다. 같은 이름의 잘못된 인덱스도 IF NOT EXISTS로 보완되지 않는다. 기존 좌표의 location 역채움도 수행하지 않으므로 기존 데이터가 있으면 적용 후 불일치 쿼리를 확인한다.
- 두 테이블에 RLS를 활성화하고 PUBLIC/anon/authenticated의 테이블 권한을 철회한 후 anon/authenticated에 SELECT를 부여한다. 시설·운영시간의 모든 행을 두 클라이언트 역할이 읽을 수 있게 된다. 공개하면 안 되는 필드가 기존 테이블에 있는지 확인한다.
- service_role은 두 테이블 CRUD, 적재/통계/주변 RPC 실행 권한을 가진다. 클라이언트 역할에는 해당 RPC 실행 권한이 없다. Secret Key는 백엔드 전용이다.
- 같은 이름의 읽기 정책·트리거 충돌은 일부 검사하지만, 다른 이름의 기존 정책은 그대로 남는다. 이관 전후 전체 정책과 실효 권한을 확인해야 한다. 일반 사용자 INSERT/UPDATE/DELETE 권한은 모두 false여야 한다.

## 적용 후 정상 기준

- `public.facilities`, `public.facility_access_hours`가 존재하고 둘 다 RLS 활성화.
- 시설 UUID PK, `(facility_type, source_id)` 유일 제약, 운영시간 `(facility_id, weekday)` PK 및 시설 FK, 좌표·시설 종류·운영시간 제약 존재.
- 시설 종류/source_id 인덱스와 `facilities_location_gist`, 위치 갱신 트리거 존재.
- anon/authenticated는 두 테이블 SELECT만 가능. service_role은 필요한 CRUD 및 RPC 실행 가능.
- 기존 데이터가 있었다면 적용 전후 건수 동일. 새 빈 DB라면 직접 COUNT한 AED 0건은 정상이며 적재 완료를 뜻하지 않는다.
- 중복·좌표 범위 오류·좌표/location 불일치 0건. 누락 좌표는 별도 집계하고 임의로 0으로 바꾸지 않는다.
- 주변 검색 함수는 빈 DB에서 JSON 배열 `[]`를 반환할 수 있다. distance_m는 지리적 미터 거리이며 도보 시간은 생성하지 않는다.

핵심 검증 SQL (전체 점검은 verify_facilities.sql 사용):

```sql
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours');
SELECT count(*) AS aed_count FROM public.facilities WHERE facility_type = 'aed';
SELECT count(*) AS access_hours_count FROM public.facility_access_hours;
SELECT public.get_aed_import_stats();
SELECT public.nearby_facilities(37.5665, 126.9780, 'aed', 3000);
```

## 적용 후 SDK 재조회 (PowerShell, 저장소 루트)

```powershell
.\.venv\Scripts\python.exe backend/scripts/check_facilities_schema.py
```

이 스크립트는 두 테이블 exact count, AED exact count, 통계/주변 검색 RPC만 읽는다. 빈 DB도 검증할 수 있고 오류 원문·비밀값은 출력하지 않는다. 실제 SQL Editor 적용 전에는 실패할 수 있으며, 실패를 적용 완료로 간주하지 않는다. SDK 점검은 전체 테이블 목록이나 RLS 카탈로그 검증을 대체하지 않는다. 실데이터 API 응답 검증 및 AED 적재는 별도 단계다.
