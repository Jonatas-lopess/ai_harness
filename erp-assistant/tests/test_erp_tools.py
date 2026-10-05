from datetime import date
import psycopg
from pydantic import BaseModel
from pytest import MonkeyPatch, fixture, mark

import erp_tools
from erp_tools import (
    LowStockOutput,
    OpenPurchaseOrdersOutput,
    RecentSalesOutput,
    SupplierLeadTimeOutput,
    erp_registry,
)
from settings import get_settings
from tools import ToolContext, ToolError, ToolRegistry, connect_readonly

AS_OF = date(2026, 1, 31)

pytestmark = mark.integration


@fixture
def ctx():
    with connect_readonly(get_settings().database_url.get_secret_value()) as conn:
        yield ToolContext(conn=conn, as_of=AS_OF)


@fixture
def registry() -> ToolRegistry:
    return erp_registry()


def _call(registry: ToolRegistry, ctx: ToolContext, name: str, args: dict[str, object]) -> BaseModel:
    return registry.call(name, ctx, args)


def test_registry_exposes_the_four_tools(registry: ToolRegistry):
    names = [s["name"] for s in registry.schemas()]

    assert names == ["low_stock", "recent_sales", "open_purchase_orders", "supplier_lead_time"]


def test_low_stock_orders_by_suggested_qty(registry: ToolRegistry, ctx: ToolContext):
    result = _call(registry, ctx, "low_stock", {})

    assert isinstance(result, LowStockOutput)
    assert [(i.name, i.suggested_qty) for i in result.items] == [("rupture", 250), ("received-po", 240)]
    assert result.total == 2
    assert result.truncated is False


def test_low_stock_reports_truncation(
    registry: ToolRegistry, ctx: ToolContext, monkeypatch: MonkeyPatch
):
    monkeypatch.setattr(erp_tools, "MAX_LOW_STOCK_ITEMS", 1)

    result = _call(registry, ctx, "low_stock", {})

    assert isinstance(result, LowStockOutput)
    assert len(result.items) == 1
    assert result.total == 2
    assert result.truncated is True


def test_recent_sales_aggregates_daily_and_respects_window(registry: ToolRegistry, ctx: ToolContext):
    result = _call(registry, ctx, "recent_sales", {"product_id": 3, "days": 30})

    assert isinstance(result, RecentSalesOutput)
    # as vendas de 999 (fora da janela e no próprio as_of) não entram
    assert result.total_quantity == 30
    assert [d.quantity for d in result.daily] == [15, 15]


def test_recent_sales_unknown_product_is_tool_error(registry: ToolRegistry, ctx: ToolContext):
    result = _call(registry, ctx, "recent_sales", {"product_id": 99})

    assert isinstance(result, ToolError)
    assert "99" in result.error


def test_recent_sales_days_above_cap_is_tool_error(registry: ToolRegistry, ctx: ToolContext):
    result = _call(registry, ctx, "recent_sales", {"product_id": 1, "days": 500})

    assert isinstance(result, ToolError)
    assert "days" in result.error


def test_open_purchase_orders_only_counts_open(registry: ToolRegistry, ctx: ToolContext):
    covered = _call(registry, ctx, "open_purchase_orders", {"product_id": 2})
    cancelled = _call(registry, ctx, "open_purchase_orders", {"product_id": 1})
    received = _call(registry, ctx, "open_purchase_orders", {"product_id": 4})

    assert isinstance(covered, OpenPurchaseOrdersOutput)
    assert covered.total_quantity == 100
    assert isinstance(cancelled, OpenPurchaseOrdersOutput)
    assert cancelled.orders == []
    assert isinstance(received, OpenPurchaseOrdersOutput)
    assert received.orders == []


def test_supplier_lead_time(registry: ToolRegistry, ctx: ToolContext):
    result = _call(registry, ctx, "supplier_lead_time", {"supplier_id": 2})

    assert isinstance(result, SupplierLeadTimeOutput)
    assert result.lead_time_days == 10


def test_supplier_lead_time_unknown_supplier_is_tool_error(registry: ToolRegistry, ctx: ToolContext):
    result = _call(registry, ctx, "supplier_lead_time", {"supplier_id": 99})

    assert isinstance(result, ToolError)


def test_tools_work_inside_a_readonly_connection(ctx: ToolContext):
    row = ctx.conn.execute("SHOW default_transaction_read_only").fetchone()

    assert row is not None
    assert row[0] == "on"
    assert isinstance(ctx.conn, psycopg.Connection)
