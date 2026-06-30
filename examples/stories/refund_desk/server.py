"""Resolver DI: the refund amount is computed by resolvers from the order record — `cents` never appears in the
tool's input schema, so the model cannot supply or inflate it."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel

from mcp.server.mcpserver import (
    AcceptedElicitation,
    Elicit,
    ElicitationResult,
    MCPServer,
    RequestStateSecurity,
    Resolve,
)
from mcp.server.mcpserver.exceptions import ToolError
from stories._hosting import run_server_from_args


@dataclass(frozen=True)
class Line:
    sku: str
    cents: int
    physical: bool


@dataclass(frozen=True)
class Order:
    order_id: str
    lines: tuple[Line, ...]


ORDERS: dict[str, Order] = {
    "ORD-7001": Order("ORD-7001", (Line("ebook-fieldnotes", 1500, physical=False),)),
    "ORD-7002": Order(
        "ORD-7002",
        (
            Line("enamel-mug", 1800, physical=True),
            Line("canvas-tote", 2400, physical=True),
            Line("sticker-pack", 600, physical=False),
        ),
    ),
}


class Scope(BaseModel):
    """Which items to refund: the whole order, or a single SKU."""

    full: bool
    sku: str = ""


class RestockChoice(BaseModel):
    restock: bool


class Receipt(BaseModel):
    order_id: str
    refunded_cents: int
    restocked: bool
    reason: str


def load_order(order_id: str) -> Order:
    order = ORDERS.get(order_id)
    if order is None:
        raise ToolError(f"unknown order {order_id!r}")
    return order


def refund_scope(order_id: str, order: Annotated[Order, Resolve(load_order)]) -> Scope | Elicit[Scope]:
    if len(order.lines) == 1:
        return Scope(full=True)
    skus = ", ".join(line.sku for line in order.lines)
    return Elicit(f"{order_id} has several items ({skus}). Refund the whole order, or one SKU?", Scope)


def _scoped(order: Order, scope: Scope) -> tuple[Line, ...]:
    """The lines a scope covers. The SKU was typed by a human — validate it against the order."""
    if scope.full:
        return order.lines
    lines = tuple(line for line in order.lines if line.sku == scope.sku)
    if not lines:
        raise ToolError(f"order has no item {scope.sku!r}")
    return lines


def refund_amount(
    order: Annotated[Order, Resolve(load_order)],
    scope: Annotated[Scope, Resolve(refund_scope)],
) -> int:
    return sum(line.cents for line in _scoped(order, scope))


def ask_restock(
    order: Annotated[Order, Resolve(load_order)],
    scope: Annotated[Scope, Resolve(refund_scope)],
) -> RestockChoice | Elicit[RestockChoice]:
    physical = [line.sku for line in _scoped(order, scope) if line.physical]
    if not physical:
        return RestockChoice(restock=False)
    return Elicit(f"The refund includes physical items ({', '.join(physical)}). Return them to stock?", RestockChoice)


def build_server() -> MCPServer:
    # At 2026 the elicited answers ride between rounds inside requestState; resolver
    # tools refuse to register without protection. See mrtr/ for the full story.
    mcp = MCPServer("refund-desk", request_state_security=RequestStateSecurity.ephemeral())

    @mcp.tool(description="Refund an order. The amount comes from the order record, not from the caller.")
    def refund_order(
        order_id: str,
        reason: str,
        cents: Annotated[int, Resolve(refund_amount)],
        restock: Annotated[ElicitationResult[RestockChoice], Resolve(ask_restock)],
    ) -> Receipt:
        # `restock` keeps the full elicitation outcome: a declined restock still refunds. A plain
        # (non-Elicit) resolver return arrives wrapped as an accepted outcome, so the fast path
        # lands in the same `AcceptedElicitation` branch.
        restocked = isinstance(restock, AcceptedElicitation) and restock.data.restock
        return Receipt(order_id=order_id, refunded_cents=cents, restocked=restocked, reason=reason)

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
