# API 요청 횟수 제한

## 적용 범위와 우선순위

FastAPI의 요청 제한은 다음 세 경로가 IP별 단일 슬라이딩 윈도우를 공유한다.

- `POST /api/aeds/recommendations`
- `GET /api/dev/walking-route`
- `GET /api/dev/driving-route`

초기값은 연속 60초 동안 대상 API 요청 시도를 최대 10회 허용한다. 제한을 초과한 요청은 카운터에 추가하지 않고 `429`, `Retry-After`, `Cache-Control: no-store`, `X-RateLimit-Source: lifetime`을 반환한다. 가장 오래된 허용 요청이 만료되는 시각까지 올림한 초가 `Retry-After` 값이다. 시각은 Redis 서버 시각을 사용하므로 앱 인스턴스 시계 차이는 카운터에 영향을 주지 않는다. `OPTIONS`, `/health`, 그 밖의 경로와 메서드는 이 정책에서 제외한다.

요청 우선순위는 제한 게이트 → 본문 크기·JSON 검사 → FastAPI의 기존 요청 검증·의존성·인증 처리 → 엔드포인트 동작이다. 대상 경로의 입력 오류와 인증 실패도 요청 한도에 포함한다. 한도를 넘긴 요청은 입력 오류나 권한 오류보다 `429`가 먼저 반환되며, 해당 요청의 엔드포인트 의존성은 실행되지 않는다. 한도 이내의 잘못된 본문은 기존 `422` 동작을 유지한다. FastAPI가 모델 오류 응답 전에 의존성 팩토리를 실행할 수 있지만, 회귀 테스트는 잘못된 추천 본문이 시설 RPC와 외부 경로 공급자 호출을 만들지 않는지 확인한다. 차단된 요청은 DB/RPC 및 외부 경로 공급자를 호출하지 않는다. 경로 공급자 자체의 `429`에는 `X-RateLimit-Source: upstream`을 표시하고 사용자별 제한 대기시간으로 취급하지 않는다.

## IP 식별과 공유 저장소

Vercel은 배포 요청의 `X-Forwarded-For`를 요청자의 공개 IP로 덮어쓰고, 상위 프록시의 IP 전달은 별도 Trusted Proxy 조건이 필요하다고 설명한다. 따라서 Vercel 구성에서는 `RATE_LIMIT_TRUSTED_PROXY=vercel`을 명시할 때만 단일 IP 형식의 `X-Forwarded-For`를 사용한다. 누락되거나 여러 주소가 들어오면 차단 판단을 안전하게 할 수 없으므로 보호 경로는 `503`이다. 그 외 로컬 직접 실행은 소켓 peer 주소(`peer`)를 사용하고 전달 헤더를 무시한다. IP는 IPv4/IPv6 표기로 정규화하며 IPv4-mapped IPv6는 IPv4와 같은 식별자로 정규화한다. 저장 키에는 `RATE_LIMIT_HMAC_SECRET`을 사용한 HMAC만 포함한다.

프로덕션과 Preview는 모든 인스턴스가 공유하는 Upstash Redis REST 저장소를 사용한다. Redis Lua `EVAL` 한 번으로 오래된 이벤트 제거, 제한 판정, 기록, TTL 부여를 원자적으로 처리한다. IP별로 최대 설정 한도만 저장하고 마지막 허용 요청 후 윈도우만큼 TTL을 둔다. 저장소 오류·잘못된 응답·필수 설정 누락은 자동으로 제한을 해제하지 않고 보호 API에 `503`을 반환한다. 프로세스 메모리 저장소는 `APP_ENV=development|local|test`와 `RATE_LIMIT_STORE=memory`가 명시된 비배포 환경에서만 사용할 수 있다.

Vercel의 요청 헤더 계약과 상위 프록시 주의사항은 [Request headers](https://vercel.com/docs/headers/request-headers)에 설명되어 있다. Upstash의 REST 명령 형식과 HTTP 인증은 [REST API](https://upstash.com/docs/redis/features/restapi), Lua 기반 원자 연산은 [Lua scripting](https://upstash.com/blog/lua-scripting-on-upstash-redis-atomic-operations-over-http)을 참고한다.

## 설정

로컬 개발에서는 `backend/.env.example`의 `RATE_LIMIT_STORE=memory`, `RATE_LIMIT_TRUSTED_PROXY=peer`, 32바이트 이상 `RATE_LIMIT_HMAC_SECRET`을 로컬 전용 `.env`에 설정한다. 이 값이나 실제 비밀값을 Git에 추가하지 않는다.

Vercel Production과 Preview에는 다음 서버 전용 환경변수를 각각 설정한다. 값은 빌드 로그나 프런트엔드에 노출하지 않는다.

| 이름 | 목적 | 기본/범위 |
| --- | --- | --- |
| `RATE_LIMIT_STORE` | 저장소 선택 | `upstash` |
| `RATE_LIMIT_TRUSTED_PROXY` | IP 출처 | `vercel` |
| `RATE_LIMIT_LIMIT` | 허용 횟수 | `10` |
| `RATE_LIMIT_WINDOW_SECONDS` | 슬라이딩 구간 | `60` |
| `RATE_LIMIT_HMAC_SECRET` | IP 키 HMAC 비밀 | 임의의 강한 비밀값, 최소 32바이트 |
| `UPSTASH_REDIS_REST_URL` | 기존 Redis REST endpoint | HTTPS endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | 서버 전용 Redis 인증 | 표준 쓰기 토큰 |

새 데이터베이스를 만들거나 서비스에 가입하지 않았다. 배포 계정에 이미 공유 Redis가 있는지 확인하고, 없다면 운영 담당자가 승인된 저장소와 비밀값을 마련해야 한다. 적용은 미리보기 배포에서 먼저 확인한다.

## 브라우저 동작

프런트엔드는 자체 제한 응답의 `Retry-After` 초 또는 HTTP 날짜를 읽고 1초~1시간 범위로 제한해 대기 시간을 표시한다. 형식이 없거나 잘못된 값은 60초를 사용한다. 대기 중 경로 조회·비교 버튼을 비활성화하고 요청 함수도 네트워크 호출을 막는다. 타이머가 끝나면 경로 버튼이 다시 활성화된다. 시설 검색·상세 같은 다른 기능은 계속 동작한다. 프런트엔드는 `X-RateLimit-Source: lifetime`에서만 제한 대기 상태를 설정하므로 공급자 자체 `429`와 구분한다.

Vercel Services 구성은 프런트엔드와 FastAPI를 같은 프로젝트의 별도 서비스로 둘 수 있고 top-level rewrite로 API 경로를 FastAPI에 전달한다. 실제 프로젝트 적용 여부는 프로젝트 설정과 프로덕션 배포 정보를 확인해야 한다.

개발 환경의 `frontend/vite.config.ts`는 `/api/dev/walking-route`와 `/api/dev/driving-route`를 Vite `configureServer`에서 직접 프록시한다. 이 개발 전용 경로는 FastAPI 요청 제한을 거치지 않는다. 프로덕션 빌드는 Vite 개발 미들웨어를 포함하지 않고, 공개 `vercel.json`의 `/api/*` rewrite가 FastAPI `routes_proxy`로 전달한다. Vite 개발 경로를 운영 제한의 검증 근거로 사용하지 않는다.

## 검증 범위

`backend/tests/test_rate_limit.py`는 Mock 메모리 저장소, 가짜 시계, TestClient 및 in-process ASGI 앱을 사용한다. 여러 앱 인스턴스는 같은 Mock 저장소를 공유하도록 검증한다. 이는 실제 Upstash/Redis 동시성·장애·TTL을 검증한 결과가 아니다. 실제 공유 저장소 검증은 비밀값을 읽거나 출력하지 않는 격리 Redis 설정에서 별도로 수행한다.

프런트엔드 단위 테스트는 `npm run test:rate-limit`로 실행한다. 배포 미리보기에서는 정상 요청 10회, 11번째 `429`와 `Retry-After`, 경로 버튼 대기/재활성화, 공급자 제한 응답 구분, 시설 조회 지속 여부를 DevTools Network에서 확인한다. 실제 공개 도메인에는 부하 테스트를 하지 않는다.
