-- 초기 재고. **원본(쓰기 담당) DB 에만** 실행한다 — 사본은 논리 복제로 받는다(schema.sql 머리말).
-- 다시 실행해도 기존 재고를 덮어쓰지 않는다(ON CONFLICT DO NOTHING).
--   psql "$ORIGIN_DATABASE_URL" -f sql/seed.sql
INSERT INTO shop.items (sku, name, initial_stock, stock) VALUES
  ('apple',  '사과', 10, 10),
  ('pear',   '배',   10, 10),
  ('orange', '귤',   10, 10)
ON CONFLICT (sku) DO NOTHING;
