"""재고(shop.items)·주문(shop.orders) 쓰기와 대조."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg_pool import AsyncConnectionPool

_RECENT_LIMIT = 10
# 같은 키가 동시에 오면 한쪽의 INSERT 가 고유 색인에 걸린다 → 롤백(재고도 되돌아감) 뒤 다시 찾는다.
_MAX_ORDER_ATTEMPTS = 3

_FIND_BY_REQUEST_ID_SQL = """
SELECT order_id, sku, qty, ordered_at, written_env FROM shop.orders WHERE request_id = %s
"""

_TAKE_STOCK_SQL = """
UPDATE shop.items SET stock = stock - %s WHERE sku = %s AND stock >= %s RETURNING stock
"""

_ITEM_EXISTS_SQL = "SELECT stock FROM shop.items WHERE sku = %s"

_INSERT_ORDER_SQL = """
INSERT INTO shop.orders (request_id, sku, qty, written_env)
VALUES (%s, %s, %s, %s)
RETURNING order_id, ordered_at
"""

_ITEMS_SQL = """
SELECT i.sku, i.name, i.initial_stock, i.stock,
       COALESCE(sum(o.qty), 0)::int AS ordered, count(o.order_id)::int AS orders
FROM shop.items i LEFT JOIN shop.orders o ON o.sku = i.sku
GROUP BY i.sku, i.name, i.initial_stock, i.stock
ORDER BY i.sku
"""

_RECENT_SQL = """
SELECT order_id, sku, qty, written_env, ordered_at, request_id
FROM shop.orders ORDER BY ordered_at DESC LIMIT %s
"""


class UnknownItem(Exception):
    pass


class OutOfStock(Exception):
    def __init__(self, stock: int) -> None:
        super().__init__(f"stock {stock}")
        self.stock = stock


@dataclass(frozen=True, slots=True)
class PlacedOrder:
    order_id: UUID
    sku: str
    qty: int
    ordered_at: datetime
    environment: str
    stock_after: int | None
    created: bool


@dataclass(frozen=True, slots=True)
class ItemRow:
    sku: str
    name: str
    initial_stock: int
    stock: int
    ordered: int
    orders: int

    @property
    def consistent(self) -> bool:
        """처음 재고 − 주문 수량 합 = 지금 재고.

        결과만 복제하다 주문을 잃으면 재고도 같이 잃어 여기는 맞게 나온다 → 받은 주문이
        사라졌는지는 요청 키(request_id)로 본다. 그래서 재생이 필요하다.
        """
        return self.initial_stock - self.ordered == self.stock


@dataclass(frozen=True, slots=True)
class RecentOrder:
    order_id: UUID
    sku: str
    qty: int
    environment: str
    ordered_at: datetime
    request_id: str | None


@dataclass(frozen=True, slots=True)
class ShopSummary:
    items: list[ItemRow]
    recent: list[RecentOrder]
    total_orders: int


async def place_order(
    pool: AsyncConnectionPool, environment: str, sku: str, qty: int, request_id: str | None
) -> PlacedOrder:
    """재고를 qty 만큼 줄이고 주문을 남긴다(한 트랜잭션).

    같은 request_id 면 재고를 다시 줄이지 않고 처음 주문을 돌려준다.
    """
    for attempt in range(1, _MAX_ORDER_ATTEMPTS + 1):
        try:
            async with pool.connection() as conn, conn.transaction():
                if request_id is not None:
                    cur = await conn.execute(_FIND_BY_REQUEST_ID_SQL, (request_id,))
                    found = await cur.fetchone()
                    if found is not None:
                        return PlacedOrder(
                            order_id=found[0],
                            sku=found[1],
                            qty=found[2],
                            ordered_at=found[3],
                            environment=found[4],
                            stock_after=None,
                            created=False,
                        )
                cur = await conn.execute(_TAKE_STOCK_SQL, (qty, sku, qty))
                taken = await cur.fetchone()
                if taken is None:
                    cur = await conn.execute(_ITEM_EXISTS_SQL, (sku,))
                    item = await cur.fetchone()
                    if item is None:
                        raise UnknownItem(sku)
                    raise OutOfStock(item[0])
                cur = await conn.execute(_INSERT_ORDER_SQL, (request_id, sku, qty, environment))
                row = await cur.fetchone()
        except psycopg.errors.UniqueViolation:
            if attempt == _MAX_ORDER_ATTEMPTS:
                raise
            continue
        if row is None:
            raise RuntimeError("INSERT … RETURNING returned no row")
        return PlacedOrder(
            order_id=row[0],
            sku=sku,
            qty=qty,
            ordered_at=row[1],
            environment=environment,
            stock_after=taken[0],
            created=True,
        )
    raise AssertionError("unreachable")


async def read_summary(pool: AsyncConnectionPool) -> ShopSummary:
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        items = await (await conn.execute(_ITEMS_SQL)).fetchall()
        recent = await (await conn.execute(_RECENT_SQL, (_RECENT_LIMIT,))).fetchall()
    return ShopSummary(
        items=[ItemRow(*r) for r in items],
        recent=[RecentOrder(*r) for r in recent],
        total_orders=sum(r[5] for r in items),
    )
