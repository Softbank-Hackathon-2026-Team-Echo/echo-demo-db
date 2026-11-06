"""시작 때 스키마 맞춤(AUTO_MIGRATE)을 확인한다.

초기 재고는 넣지 않는다(sql/seed.sql 은 원본에만).
"""

import psycopg
import pytest

from app.db import read_schema_sql
from tests.support import make_settings, running_client

pytestmark = pytest.mark.integration


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = 'shop' AND table_name = %s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


async def test_startup_creates_schema_without_seed(
    database_url: str, admin_conn: psycopg.Connection
) -> None:
    admin_conn.execute("DROP SCHEMA IF EXISTS shop CASCADE")

    async with running_client(make_settings(database_url)) as client:
        summary = (await client.get("/api/summary")).json()

    assert _columns(admin_conn, "items") == ["sku", "name", "initial_stock", "stock"]
    assert _columns(admin_conn, "orders") == [
        "order_id",
        "request_id",
        "sku",
        "qty",
        "ordered_at",
        "written_env",
    ]
    assert summary["items"] == []  # 사본에 행이 먼저 생기면 복제가 겹친다 → 시작 때 넣지 않는다
    seqs = admin_conn.execute(
        "SELECT count(*) FROM pg_sequences WHERE schemaname = 'shop'"
    ).fetchone()
    assert seqs == (0,)  # 시퀀스 없음(승격 뒤 번호 겹침 방지)


def test_schema_sql_twice_is_safe(admin_conn: psycopg.Connection) -> None:
    admin_conn.execute(read_schema_sql().encode())
    admin_conn.execute(read_schema_sql().encode())
    idx = admin_conn.execute(
        "SELECT count(*) FROM pg_indexes WHERE indexname = 'orders_request_id_key'"
    ).fetchone()
    assert idx == (1,)
