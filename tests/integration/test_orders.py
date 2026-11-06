"""주문·재고·멱등 주문을 PgBouncer(transaction 모드)를 거친 실제 DB 로 확인한다."""

import asyncio
from pathlib import Path

import psycopg
import pytest

from tests.support import make_settings, running_client

pytestmark = pytest.mark.integration

SEED_SQL = (Path(__file__).resolve().parents[2] / "sql" / "seed.sql").read_text(encoding="utf-8")


@pytest.fixture
def seeded(admin_conn: psycopg.Connection) -> psycopg.Connection:
    from app.db import read_schema_sql

    admin_conn.execute("DROP SCHEMA IF EXISTS shop CASCADE")
    admin_conn.execute(read_schema_sql().encode())
    admin_conn.execute(SEED_SQL.encode())
    return admin_conn


def _stock(conn: psycopg.Connection, sku: str) -> int:
    row = conn.execute("SELECT stock FROM shop.items WHERE sku = %s", (sku,)).fetchone()
    assert row is not None
    return int(row[0])


async def test_order_takes_stock_and_records_order(
    database_url: str, seeded: psycopg.Connection
) -> None:
    async with running_client(make_settings(database_url)) as client:
        r = await client.post("/api/orders", json={"sku": "apple", "qty": 2})
        summary = (await client.get("/api/summary")).json()

    assert r.status_code == 201
    body = r.json()
    assert set(body) == {
        "orderId",
        "sku",
        "qty",
        "environment",
        "hostname",
        "orderedAt",
        "stockAfter",
    }
    assert (body["sku"], body["qty"], body["stockAfter"]) == ("apple", 2, 8)
    assert _stock(seeded, "apple") == 8
    apple = next(i for i in summary["items"] if i["sku"] == "apple")
    assert (apple["stock"], apple["ordered"], apple["orders"], apple["consistent"]) == (
        8,
        2,
        1,
        True,
    )
    assert summary["consistent"] is True
    assert summary["totalOrders"] == 1


async def test_same_key_twice_takes_stock_once(
    database_url: str, seeded: psycopg.Connection
) -> None:
    async with running_client(make_settings(database_url)) as client:
        first = await client.post(
            "/api/orders", json={"sku": "pear", "qty": 3}, headers={"Idempotency-Key": "o-1"}
        )
        again = await client.post(
            "/api/orders", json={"sku": "pear", "qty": 3}, headers={"Idempotency-Key": "o-1"}
        )

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["orderId"] == first.json()["orderId"]
    assert again.json()["stockAfter"] is None
    assert _stock(seeded, "pear") == 7


async def test_same_key_concurrent_takes_stock_once(
    database_url: str, seeded: psycopg.Connection
) -> None:
    async with running_client(make_settings(database_url)) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/api/orders", json={"sku": "apple"}, headers={"Idempotency-Key": "same"}
                )
                for _ in range(10)
            )
        )

    assert sorted(r.status_code for r in responses) == [200] * 9 + [201]
    assert len({r.json()["orderId"] for r in responses}) == 1
    assert _stock(seeded, "apple") == 9


async def test_out_of_stock_returns_409_and_keeps_stock(
    database_url: str, seeded: psycopg.Connection
) -> None:
    async with running_client(make_settings(database_url)) as client:
        ok = await client.post("/api/orders", json={"sku": "orange", "qty": 10})
        over = await client.post("/api/orders", json={"sku": "orange", "qty": 1})
        unknown = await client.post("/api/orders", json={"sku": "melon"})

    assert ok.status_code == 201
    assert (over.status_code, over.json()) == (409, {"error": "OUT_OF_STOCK"})
    assert (unknown.status_code, unknown.json()) == (404, {"error": "UNKNOWN_ITEM"})
    assert _stock(seeded, "orange") == 0


async def test_concurrent_orders_never_oversell(
    database_url: str, seeded: psycopg.Connection
) -> None:
    async with running_client(make_settings(database_url)) as client:
        responses = await asyncio.gather(
            *(client.post("/api/orders", json={"sku": "apple"}) for _ in range(15))
        )

    assert sorted(r.status_code for r in responses) == [201] * 10 + [409] * 5
    assert _stock(seeded, "apple") == 0


async def test_replay_skips_existing_and_applies_missing(
    database_url: str, seeded: psycopg.Connection
) -> None:
    """재생 흉내: 주문 1·2·3 은 이미 있고 1~5 를 순서대로 다시 보내면 4·5 만 재고를 줄인다."""
    async with running_client(make_settings(database_url)) as client:
        for i in range(1, 4):
            await client.post(
                "/api/orders", json={"sku": "apple"}, headers={"Idempotency-Key": f"r-{i}"}
            )
        replayed = [
            await client.post(
                "/api/orders", json={"sku": "apple"}, headers={"Idempotency-Key": f"r-{i}"}
            )
            for i in range(1, 6)
        ]
        summary = (await client.get("/api/summary")).json()

    assert [r.status_code for r in replayed] == [200, 200, 200, 201, 201]
    assert _stock(seeded, "apple") == 5
    assert summary["consistent"] is True


async def test_key_too_long_returns_400(database_url: str, seeded: psycopg.Connection) -> None:
    async with running_client(make_settings(database_url)) as client:
        r = await client.post(
            "/api/orders", json={"sku": "apple"}, headers={"Idempotency-Key": "x" * 201}
        )
    assert (r.status_code, r.json()) == (400, {"error": "REQUEST_ID_TOO_LONG"})
    assert _stock(seeded, "apple") == 10


async def test_flag_off_ignores_key(database_url: str, seeded: psycopg.Connection) -> None:
    async with running_client(make_settings(database_url, idempotent_writes=False)) as client:
        a = await client.post("/api/orders", json={"sku": "pear"}, headers={"Idempotency-Key": "k"})
        b = await client.post("/api/orders", json={"sku": "pear"}, headers={"Idempotency-Key": "k"})
    assert (a.status_code, b.status_code) == (201, 201)
    assert _stock(seeded, "pear") == 8
