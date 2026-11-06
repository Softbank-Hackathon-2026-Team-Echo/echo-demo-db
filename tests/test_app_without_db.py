"""DB 가 없을 때도 프로세스가 뜨고, 생존 확인만 성공하는지 본다."""

import re
from collections.abc import AsyncIterator

import httpx
import pytest

from app.shop import ItemRow
from tests.support import make_settings, running_client

# 아무것도 듣지 않는 포트. 연결은 바로 거절된다.
UNREACHABLE_DATABASE_URL = "postgresql://demo:demo@127.0.0.1:1/demo?connect_timeout=1"


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    settings = make_settings(
        UNREACHABLE_DATABASE_URL, db_pool_timeout_seconds=0.3, readiness_timeout_seconds=0.5
    )
    async with running_client(settings) as c:
        yield c


async def test_healthz_without_db_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


async def test_readyz_without_db_returns_unavailable(client: httpx.AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


async def test_create_order_without_db_returns_503(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/orders", json={"sku": "apple"})
    assert response.status_code == 503
    assert response.json() == {"error": "DB_UNAVAILABLE"}


async def test_summary_without_db_returns_503(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/summary")
    assert response.status_code == 503
    assert response.json() == {"error": "DB_UNAVAILABLE"}


async def test_info_returns_environment_hostname_version(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/info")
    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "aws-tokyo"
    assert body["version"] == "test"
    assert isinstance(body["hostname"], str) and body["hostname"]


async def test_info_blank_environment_returns_unknown() -> None:
    settings = make_settings(
        UNREACHABLE_DATABASE_URL, echo_environment="  ", app_version="", db_pool_timeout_seconds=0.3
    )
    async with running_client(settings) as client:
        body = (await client.get("/api/info")).json()
    assert body["environment"] == "unknown"
    assert body["version"] == "dev"


async def test_index_serves_page_without_external_resources(client: httpx.AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    for text in (
        "재고",
        "응답 환경",
        "주문",
        "/api/orders",
        "/api/summary",
    ):
        assert text in html
    # 외부 CDN·폰트·스크립트를 쓰지 않는다(차단 환경에서도 뜨게).
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html)
    assert not re.search(r"""@import|url\(\s*["']?(https?:)?//""", html)


def test_item_consistent_when_initial_minus_ordered_equals_stock() -> None:
    assert ItemRow("apple", "사과", 10, 8, 2, 1).consistent
    assert not ItemRow("apple", "사과", 10, 10, 2, 1).consistent


async def test_order_rejects_bad_quantity_without_db(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/orders", json={"sku": "apple", "qty": 0})
    assert response.status_code == 422
