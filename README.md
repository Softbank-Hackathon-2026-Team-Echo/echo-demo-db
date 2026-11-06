# echo-demo-db

Team Echo **요청 기록 재생**(echo-infra 인프라 12.4)을 보여 주는 재고·주문 앱. 도쿄 원본 DB 가 갑자기 죽어도 사용자가 이미 받은 주문이 사라지지 않고, 재고도 그만큼 줄어든 채로 서울에서 이어지는지를 화면에서 확인한다.

```text
사과 재고 10 → 주문 2 (도쿄에만 들어가고 서울로 복제되기 전) → 도쿄 DB 정지 → 서울 승격
  결과만 복제할 때:   서울 재고 10, 주문 0  — 사용자는 주문 완료를 받았는데 주문이 없다
  요청 기록 재생:     서울 재고 8,  주문 2  — 진입점이 받아 둔 주문 요청을 서울에 다시 보냄(같은 키는 건너뜀)
```

구조와 배포 방식은 [echo-demo-app](https://github.com/Softbank-Hackathon-2026-Team-Echo/echo-demo-app) 과 같다(FastAPI · psycopg · PgBouncer transaction 모드 · 정적 HTML 한 장 · Echo 플랫폼이 저장소 + 커밋으로 빌드).

## API

| 메서드·경로 | 내용 |
|---|---|
| `POST /api/orders` `{"sku": "apple", "qty": 1}` | 재고를 줄이고 주문을 남긴다(한 트랜잭션). **201** 새 주문 · **200** 같은 `Idempotency-Key`(없으면 Envoy `x-request-id`)로 이미 받은 주문(재고를 다시 줄이지 않음) · **409** `OUT_OF_STOCK` · **404** `UNKNOWN_ITEM` · **400** 키 200자 초과 · **503** DB 없음 |
| `GET /api/summary` | 상품별 처음 재고·주문 수량·지금 재고·대조(처음 − 주문 = 지금), 최근 주문 10건(요청 키·받은 환경) |
| `GET /api/info` · `/healthz` · `/readyz` · `/metrics` | echo-demo-app 과 같다 |
| `GET /` | 화면(외부 리소스 없음, 3초마다 새로고침) |

## 설정

| 환경 변수 | 뜻 | 기본 |
|---|---|---|
| `DATABASE_URL` | 그 환경 PgBouncer 의 `app` DB(echo-demo-app 과 같은 DB → 논리 복제 `echo_pub FOR ALL TABLES` 에 들어간다) | 필수 |
| `ECHO_ENVIRONMENT` | 응답 환경 이름(실행기가 넣음) | `unknown` |
| `IDEMPOTENT_WRITES` | 멱등 주문. 재생 시연 앱이라 **기본 켬** | `true` |
| `AUTO_MIGRATE` | 시작 때 `sql/schema.sql`(표만, 재고는 넣지 않음) | `true` |

## 배포 (운영, 순서 중요)

1. Echo 플랫폼에 서비스로 등록하고 두 환경(aws-tokyo · gcp-seoul)에 배포 — 변수 `DATABASE_URL` 은 echo-demo-app 과 같은 값. 뜨면서 두 DB 에 `shop` 표가 생긴다
2. **원본(도쿄 A)에만** 초기 재고: `sql/seed.sql`
3. **사본(서울 B)** 구독에 새 표를 넣는다: `ALTER SUBSCRIPTION echo_sub REFRESH PUBLICATION;` → 초기 재고가 복제돼 온다
4. 확인: 두 환경 `/api/summary` 의 재고가 같다

하지 않는 것:
- 초기 재고를 사본에 넣지 않는다 — 원본의 같은 행이 복제될 때 키가 겹쳐 구독이 멈춘다(그래서 schema.sql 에 seed 가 없다)
- 시퀀스를 쓰지 않는다(주문 id = UUID) — 논리 복제는 시퀀스 값을 옮기지 않아 승격 뒤 번호가 겹친다

## 재생 시연

echo-infra `replication/k8s/scripts/promote-with-replay.sh`(진입점 기록 켬 → 도쿄 DB 정지 → 승격 + 재생). 재생은 메서드·경로·본문·멱등 키를 그대로 다시 보내므로 이 앱의 `POST /api/orders` 도 그대로 재생된다.

## 로컬

```bash
docker compose up -d --wait db pgbouncer            # PostgreSQL :55434, PgBouncer :56433
psql postgresql://demo:demo@127.0.0.1:55434/demo -f sql/schema.sql -f sql/seed.sql
ECHO_ENVIRONMENT=aws-tokyo docker compose up -d --wait   # http://localhost:8081
# 시험
TEST_DATABASE_URL=postgresql://demo:demo@127.0.0.1:56433/demo uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```
