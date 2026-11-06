-- echo-demo-db 재고·주문. 앱이 시작할 때(AUTO_MIGRATE=true) 같은 파일을 실행한다. 여러 번 실행해도 안전하다(IF NOT EXISTS).
-- 논리 복제는 DDL 을 옮기지 않으므로 두 DB(원본·사본) 모두 이 파일을 먼저 적용하고, 사본 구독을 REFRESH 한다(README "배포").
-- 시퀀스를 쓰지 않는다(주문 id = UUID): 논리 복제는 시퀀스 값을 옮기지 않아 승격 뒤 번호가 겹칠 수 있다.
-- 초기 재고(seed)는 여기 넣지 않는다: 사본에도 행이 생기면 원본의 같은 행이 복제될 때 키가 겹쳐 구독이 멈춘다 → sql/seed.sql 을 원본에만.
-- 스키마가 없을 때만 만든다. `CREATE SCHEMA IF NOT EXISTS` 는 이미 있어도 DB 의 CREATE 권한을 먼저 검사해,
-- 운영 앱 계정(app_rw, DB CREATE 권한 없음)으로는 늘 실패한다(11/6 운영 배포에서 확인).
-- 운영에서는 관리자가 한 번 `CREATE SCHEMA shop AUTHORIZATION app_rw` 로 만들어 둔다(README "배포").
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'shop') THEN
    CREATE SCHEMA shop;
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS shop.items (
  sku           text PRIMARY KEY,
  name          text NOT NULL,
  initial_stock integer NOT NULL CHECK (initial_stock >= 0),
  stock         integer NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS shop.orders (
  order_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id  text,
  sku         text NOT NULL REFERENCES shop.items (sku),
  qty         integer NOT NULL CHECK (qty > 0),
  ordered_at  timestamptz NOT NULL DEFAULT now(),
  written_env text NOT NULL DEFAULT 'unknown'
);

-- 멱등 주문: 같은 요청 키로 다시 오면 새 주문을 만들지 않는다(진입점 요청 기록 재생, echo-infra 인프라 12.4).
CREATE UNIQUE INDEX IF NOT EXISTS orders_request_id_key
  ON shop.orders (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS orders_ordered_at ON shop.orders (ordered_at);
