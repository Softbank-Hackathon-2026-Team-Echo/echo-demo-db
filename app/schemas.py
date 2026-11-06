"""API 응답 모양. JSON 키는 camelCase 다."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.shop import ShopSummary


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class HealthResponse(CamelModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(CamelModel):
    status: Literal["ready", "unavailable"]


class InfoResponse(CamelModel):
    environment: str
    hostname: str
    version: str


class ErrorResponse(CamelModel):
    error: str


class OrderRequest(CamelModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(default=1, ge=1, le=100)


class OrderResponse(CamelModel):
    order_id: UUID
    sku: str
    qty: int
    environment: str
    hostname: str
    ordered_at: datetime
    # 이번 요청으로 줄어든 뒤의 재고. 같은 키로 다시 온 요청(200)이면 null.
    stock_after: int | None


class ItemResponse(CamelModel):
    sku: str
    name: str
    initial_stock: int
    stock: int
    ordered: int
    orders: int
    consistent: bool


class RecentOrderResponse(CamelModel):
    order_id: UUID
    sku: str
    qty: int
    environment: str
    ordered_at: datetime
    request_id: str | None


class SummaryResponse(CamelModel):
    environment: str
    total_orders: int
    consistent: bool
    items: list[ItemResponse]
    recent: list[RecentOrderResponse]

    @classmethod
    def from_summary(cls, summary: ShopSummary, environment: str) -> "SummaryResponse":
        return cls(
            environment=environment,
            total_orders=summary.total_orders,
            consistent=all(i.consistent for i in summary.items),
            items=[
                ItemResponse(
                    sku=i.sku,
                    name=i.name,
                    initial_stock=i.initial_stock,
                    stock=i.stock,
                    ordered=i.ordered,
                    orders=i.orders,
                    consistent=i.consistent,
                )
                for i in summary.items
            ],
            recent=[
                RecentOrderResponse(
                    order_id=r.order_id,
                    sku=r.sku,
                    qty=r.qty,
                    environment=r.environment,
                    ordered_at=r.ordered_at,
                    request_id=r.request_id,
                )
                for r in summary.recent
            ],
        )
