"""Tools do pack ERP: somente leitura, entrada estreita, saída pequena e agregada."""

from dataclasses import dataclass
from datetime import date, timedelta

from psycopg.rows import class_row
from pydantic import BaseModel, Field

from replenishment import low_stock as detect_low_stock
from tools import Tool, ToolContext, ToolError, ToolInput, ToolRegistry, make_tool

MAX_LOW_STOCK_ITEMS = 50
MAX_SALES_DAYS = 90


def _product_exists(ctx: ToolContext, product_id: int) -> bool:
    row = ctx.conn.execute("SELECT 1 FROM products WHERE id = %s", (product_id,)).fetchone()
    return row is not None


def _unknown_product(product_id: int) -> ToolError:
    return ToolError(error=f"product {product_id} does not exist; get valid ids from low_stock")


# low_stock ---------------------------------------------------------------------------------


class LowStockInput(ToolInput):
    pass


class LowStockItem(BaseModel):
    product_id: int
    name: str
    on_hand: int
    open_po_qty: int
    reorder_point: int
    suggested_qty: int


class LowStockOutput(BaseModel):
    items: list[LowStockItem]
    total: int
    total_suggested_qty: int  # soma de todos os sinalizados, não só dos `items` devolvidos
    truncated: bool


def _low_stock(ctx: ToolContext, _args: LowStockInput) -> BaseModel:
    flagged = detect_low_stock(ctx.conn, ctx.as_of)
    # Prioridade decidida pelo código: maior quantidade sugerida primeiro.
    flagged.sort(key=lambda p: (-p.suggested_qty, p.product_id))
    items = [
        LowStockItem(
            product_id=p.product_id,
            name=p.name,
            on_hand=p.on_hand,
            open_po_qty=p.open_po_qty,
            reorder_point=p.reorder_point,
            suggested_qty=p.suggested_qty,
        )
        for p in flagged[:MAX_LOW_STOCK_ITEMS]
    ]
    return LowStockOutput(
        items=items,
        total=len(flagged),
        total_suggested_qty=sum(p.suggested_qty for p in flagged),
        truncated=len(flagged) > len(items),
    )


# recent_sales ------------------------------------------------------------------------------


class RecentSalesInput(ToolInput):
    product_id: int = Field(description="Product id (products.id).")
    days: int = Field(
        default=30,
        ge=1,
        le=MAX_SALES_DAYS,
        description=f"How many days back from the run date, 1 to {MAX_SALES_DAYS}.",
    )


class DailySales(BaseModel):
    sale_date: date
    quantity: int


class RecentSalesOutput(BaseModel):
    product_id: int
    days: int
    daily: list[DailySales]
    total_quantity: int


@dataclass(frozen=True)
class _DailySalesRow:
    sale_date: date
    quantity: int


_RECENT_SALES_SQL = """
SELECT sale_date, SUM(quantity)::int AS quantity
FROM sales
WHERE product_id = %(product_id)s AND sale_date >= %(start)s AND sale_date < %(as_of)s
GROUP BY sale_date
ORDER BY sale_date
"""


def _recent_sales(ctx: ToolContext, args: RecentSalesInput) -> BaseModel:
    if not _product_exists(ctx, args.product_id):
        return _unknown_product(args.product_id)
    params = {
        "product_id": args.product_id,
        "start": ctx.as_of - timedelta(days=args.days),
        "as_of": ctx.as_of,
    }
    with ctx.conn.cursor(row_factory=class_row(_DailySalesRow)) as cur:
        rows = cur.execute(_RECENT_SALES_SQL, params).fetchall()
    daily = [DailySales(sale_date=r.sale_date, quantity=r.quantity) for r in rows]
    return RecentSalesOutput(
        product_id=args.product_id,
        days=args.days,
        daily=daily,
        total_quantity=sum(d.quantity for d in daily),
    )


# open_purchase_orders ----------------------------------------------------------------------


class OpenPurchaseOrdersInput(ToolInput):
    product_id: int = Field(description="Product id (products.id).")


class OpenOrder(BaseModel):
    order_id: int
    quantity: int
    expected_date: date


class OpenPurchaseOrdersOutput(BaseModel):
    product_id: int
    orders: list[OpenOrder]
    total_quantity: int


@dataclass(frozen=True)
class _OpenOrderRow:
    order_id: int
    quantity: int
    expected_date: date


def _open_purchase_orders(ctx: ToolContext, args: OpenPurchaseOrdersInput) -> BaseModel:
    if not _product_exists(ctx, args.product_id):
        return _unknown_product(args.product_id)
    with ctx.conn.cursor(row_factory=class_row(_OpenOrderRow)) as cur:
        rows = cur.execute(
            """
            SELECT id AS order_id, quantity, expected_date
            FROM purchase_orders
            WHERE product_id = %s AND status = 'open'
            ORDER BY expected_date, id
            """,
            (args.product_id,),
        ).fetchall()
    orders = [OpenOrder(order_id=r.order_id, quantity=r.quantity, expected_date=r.expected_date) for r in rows]
    return OpenPurchaseOrdersOutput(
        product_id=args.product_id,
        orders=orders,
        total_quantity=sum(o.quantity for o in orders),
    )


# supplier_lead_time ------------------------------------------------------------------------


class SupplierLeadTimeInput(ToolInput):
    supplier_id: int = Field(description="Supplier id (suppliers.id).")


class SupplierLeadTimeOutput(BaseModel):
    supplier_id: int
    name: str
    lead_time_days: int


@dataclass(frozen=True)
class _SupplierRow:
    name: str
    lead_time_days: int


def _supplier_lead_time(ctx: ToolContext, args: SupplierLeadTimeInput) -> BaseModel:
    with ctx.conn.cursor(row_factory=class_row(_SupplierRow)) as cur:
        row = cur.execute(
            "SELECT name, lead_time_days FROM suppliers WHERE id = %s", (args.supplier_id,)
        ).fetchone()
    if row is None:
        return ToolError(error=f"supplier {args.supplier_id} does not exist")
    return SupplierLeadTimeOutput(
        supplier_id=args.supplier_id, name=row.name, lead_time_days=row.lead_time_days
    )


# registry ----------------------------------------------------------------------------------


def erp_tools() -> list[Tool]:
    return [
        make_tool(
            "low_stock",
            "Products below their reorder point as of the run date, open purchase orders already"
            + " discounted. Includes the suggested order quantity, computed by code. Highest"
            + " quantity first; `truncated` is true when the list was cut.",
            LowStockInput,
            _low_stock,
        ),
        make_tool(
            "recent_sales",
            "Units sold per day for one product over the last N days (daily totals, not raw rows).",
            RecentSalesInput,
            _recent_sales,
        ),
        make_tool(
            "open_purchase_orders",
            "Purchase orders already placed for one product and not yet received"
            + " (status open). Quantity and expected arrival date.",
            OpenPurchaseOrdersInput,
            _open_purchase_orders,
        ),
        make_tool(
            "supplier_lead_time",
            "Supplier delivery time in days.",
            SupplierLeadTimeInput,
            _supplier_lead_time,
        ),
    ]


def erp_registry() -> ToolRegistry:
    return ToolRegistry(erp_tools())
