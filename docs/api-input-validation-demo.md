# LifeTime API 입력 검증 시연

이 시연은 현재 FastAPI 라우트와 검증 모델에 TestClient로 요청합니다. DB/RPC, 관리자 인증, 보행 공급자는 모두 합성 Mock입니다. 운영 시설·Supabase·외부 경로 API에는 연결하지 않습니다. Mock 인증 토큰은 이 프로세스 안에서만 쓰이는 고정 시연값입니다.

## 실행

저장소 루트의 PowerShell에서:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe scripts\demo_input_validation.py
```

성공 시 6개 사례의 상태 코드와 누적 시설 RPC/경로 공급자 호출 수가 출력됩니다. 정상 요청은 검증을 통과해 Mock RPC를 1회 호출하고, 그 뒤의 모든 거부 사례는 누적 호출 수가 1회 그대로여야 합니다. 경로 공급자 호출 수는 모든 사례에서 0이어야 합니다. 관리자 접근 사례는 인증 Mock 조회를 거친 뒤 역할 부족으로 차단됩니다.

## 사례와 기대 결과

| 사례 | 요청 | 상태 | 차단 이유 및 호출 확인 |
| --- | --- | --- | --- |
| 정상 요청 | `POST /api/admin/facilities/{UUID}/changes`, 필수 시설 필드·7일 운영시간 | 200 | 입력 검증 후 합성 검토 RPC 1회. 운영 데이터 쓰기 없음 |
| 잘못된 좌표 | 정상 요청에서 `latitude: 91` | 422 | 위도 범위 `-90..90` 초과. 해당 요청의 시설 RPC 추가 호출 없음 |
| 추가 권한 필드 | 시설 레코드에 `role`, `approved` 추가 | 422 | 최상위/중첩 계약 외 필드 거부. RPC 추가 호출 없음 |
| 모순된 운영시간 | `schedule_status: "partial"`, `access_hours: []` | 422 | partial은 1~6 요일 필요. RPC 추가 호출 없음 |
| 본문 크기 초과 | `POST /api/aeds/recommendations`, 256KiB 초과 JSON | 413 | 실제 수신 바이트 제한. 시설 RPC와 경로 공급자 호출 없음 |
| 일반 사용자 관리자 접근 | 정상 관리자 변경 요청, 인증 Mock의 `app_metadata.role="member"` | 403 | 사용자 역할을 검사하고 거부. 시설 RPC 추가 호출 없음 |

시연 스크립트가 실제 응답 상태를 검증하며 기대값과 다르면 실패합니다. 마지막 두 호출 열은 테스트용 시설 RPC 및 경로 공급자의 누적 호출 횟수입니다. 관리자 인증 조회는 별도 Mock으로 세며 시설 데이터 RPC와 구분합니다.

## 요청 검증 정책

- JSON 본문 상한은 256KiB이며 추천 요청과 `/api/admin/` POST에 적용합니다. `Content-Length` 사전 검사 후 헤더 유무와 관계없이 실제 조각 수신량도 누적 제한합니다. 상한 초과는 413, JSON 파싱 오류는 422, JSON 외 Content-Type은 415입니다.
- JSON 중첩 깊이는 최대 64단계로 제한하며 초과 입력은 422로 거부합니다.
- 잘못된 JSON 문법·크기·Content-Type은 라우트 인증보다 바깥 미들웨어에서 먼저 거부됩니다. 문법적으로 유효한 관리자 JSON은 인증과 관리자 역할을 먼저 확인합니다. 자격 증명이 없으면 본문 필드 오류보다 401이 우선하며, 인증된 요청의 필드 오류는 422입니다.
- Validation 응답은 위치와 오류 종류만 제공하며 원 입력, 토큰, 예외 문구는 제공하지 않습니다.
- 이 검증은 로컬 FastAPI/TestClient + Mock 확인입니다. Supabase 스키마 마이그레이션이나 운영 DB 적용을 뜻하지 않습니다.

## 입력 상한과 근거

| 값 | 허용 범위 |
| --- | ---: |
| 위도 / 경도 | -90..90 / -180..180, finite number |
| `radius_m` | 1..20,000m (기존 상한 유지) |
| 관리자 이력 `limit` | 1..100 (기존 상한 유지) |
| `source_id` | 공백 제거 후 1..200자 |
| `name` | 최대 300자 |
| `address` | 최대 1,000자 |
| `contact_phone`, `emergency_phone` | 각각 최대 100자 |
| `sido`, `gugun` | 각각 최대 100자 |
| `installation_detail`, `source_name` | 각각 최대 1,000자 |
| 관리자 사유 | 공백 제거 후 1..500자 |
| 운영시간 목록 | 최대 7개, 요일은 중복 없이 1..7 |
| JSON 본문 | 대상 POST당 256KiB |

초기 문자열 상한은 저장소의 체크인된 `aed_nationwide.json` 63,518건과 `medical_nationwide.json` 530건을 읽어 확인했습니다. 관측 최대 길이는 source_id 17자, name 40자, address 91자, contact_phone 16자, emergency_phone 14자, sido/gugun 각각 9자, installation_detail 46자, source_name 27자였습니다. 공공데이터 문자열 컬럼은 SQL에서 길이 제한 없는 `text`라서 이 제한은 API/import 공통 경계 규칙입니다. 초과 값은 잘라내지 않고 거부합니다.

DB 마이그레이션은 좌표 범위·시설 종류·schedule_status·요일 범위와 중복·24시간 운영을 제약하고, 변경 검토 RPC는 known=7일, partial=1~6일, unknown=0일 및 응급실 운영시간 없음 규칙을 확인합니다. 기존 배치 RPC 한도는 1,000건, 관리자 이력 RPC 상한은 100건입니다. 이번 API 검증 추가로 DB 구조 변경은 필요하지 않습니다. 마이그레이션은 만들거나 운영에 적용하지 않았습니다.
