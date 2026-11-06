# echo-demo-db

요청 기록 재생(echo-infra 인프라 12.4)을 보여 주는 재고·주문 앱. 원본 DB 가 갑자기 죽어도 받은 주문과 재고 차감이 서울에서 이어지는지 본다. 시연용이라 인증·비밀값이 없다.

- **스택**: Python 3.13+, FastAPI, psycopg 3(+ psycopg_pool), PostgreSQL(PgBouncer transaction 모드 경유), uv. 화면은 정적 HTML 한 장
- **실행·설정·API·배포 순서**: [README.md](README.md) (여기서 중복하지 않는다)
- **바탕**: echo-demo-app 의 설정·풀·로그·지표·Dockerfile 을 그대로 가져왔다. 장부 대신 `app/shop.py`(재고·주문)

## 구조

```text
app/
├─ main.py      # 라우트: /api/orders · /api/summary · /api/info · /healthz · /readyz · /metrics · /
├─ shop.py      # 주문(재고 차감 + 멱등) · 대조
├─ schemas.py   # 응답 모양(camelCase)
├─ db.py · config.py · metrics.py · json_logging.py   # echo-demo-app 과 같음
└─ static/index.html
sql/schema.sql  # 표만(시작 때 AUTO_MIGRATE). seed 없음
sql/seed.sql    # 초기 재고 — 원본 DB 에만
```

## 핵심 원칙

- 앱은 PgBouncer(transaction 모드)로만 DB 에 붙는다: prepared statement·세션 상태·세션 잠금 없음, 트랜잭션은 `conn.transaction()` 블록으로만
- 논리 복제를 깨지 않는다: 시퀀스를 쓰지 않는다(UUID), schema.sql 에 행을 넣지 않는다(seed 는 원본에만), 칸을 더하면 사본 먼저
- 주문은 한 트랜잭션에서 `UPDATE … stock >= qty` 로 줄인 뒤 주문을 넣는다 → 과판매 없음. 같은 키는 먼저 찾고, 동시에 오면 고유 색인 충돌 → 롤백 → 다시 찾기
- 모든 함수 시그니처에 타입 힌트(mypy strict). 시각은 timezone-aware

## 도구

- `uv`. 린트 `uv run ruff check .` / 포맷 `uv run ruff format .` / 타입 `uv run mypy app` / 시험 `uv run pytest`
- 시험: `tests/integration/` 은 `TEST_DATABASE_URL`(PgBouncer 주소)에 붙고 `shop` 스키마를 지웠다 다시 만든다. `REQUIRE_DB_TESTS=1`(CI)이면 건너뛰지 않고 실패
- 커밋·PR: [.claude/rules/git-conventions.md](.claude/rules/git-conventions.md) (Conventional Commits)
