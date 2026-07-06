"""`docs/handlers/dependencies.md`: every claim the page makes, proved against the real SDK."""

from typing import Literal

import pytest
from inline_snapshot import snapshot
from mcp_types import ElicitRequestParams, ElicitResult, TextContent

from docs_src.dependencies import tutorial001, tutorial002, tutorial003
from mcp import Client
from mcp.client import ClientRequestContext

pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_resolver_fills_the_parameter_from_the_tools_own_argument() -> None:
    """tutorial001: `check_stock` receives `title` by name and its return value becomes `stock`."""
    async with Client(tutorial001.mcp) as client:
        in_stock = await client.call_tool("reserve_book", {"title": "Dune"})
        sold_out = await client.call_tool("reserve_book", {"title": "Neuromancer"})

    assert in_stock.content == [TextContent(type="text", text="Reserved 'Dune' (6 copies left).")]
    assert sold_out.content == [TextContent(type="text", text="'Neuromancer' is out of stock.")]


async def test_the_resolved_parameter_is_invisible_to_the_model() -> None:
    """tutorial001: the input schema shown on the page is exactly what `tools/list` reports."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools

    assert tool.input_schema == snapshot(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"title": {"title": "Title", "type": "string"}},
            "required": ["title"],
            "title": "reserve_bookArguments",
        }
    )


async def test_a_client_supplied_value_for_a_resolved_parameter_is_rejected() -> None:
    """tutorial001: resolved parameters are not in the schema, so extra arguments fail validation."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("reserve_book", {"title": "Dune", "stock": {"title": "Dune", "copies": 999}})

    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    # pydantic's "Extra inputs are not permitted" wording changes across versions.
    assert result.content[0].text.startswith("Error executing tool reserve_book:")


async def test_a_resolver_can_depend_on_another_resolver() -> None:
    """tutorial002: `estimate_delivery` consumes `check_stock`'s result, and the tool gets both."""
    async with Client(tutorial002.mcp) as client:
        in_stock = await client.call_tool("order_book", {"title": "Dune"})
        backorder = await client.call_tool("order_book", {"title": "Neuromancer"})

    assert in_stock.content == [TextContent(type="text", text="Ordered 'Dune'; it arrives tomorrow.")]
    assert backorder.content == [
        TextContent(type="text", text="'Neuromancer' is on backorder; it would arrive in 2-3 weeks.")
    ]


async def test_a_shared_dependency_runs_once_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """tutorial002: `stock` and `delivery` both need `check_stock`; one call, one inventory lookup."""

    class CountingInventory:
        def __init__(self, data: dict[str, int]) -> None:
            self.data = data
            self.lookups: list[str] = []

        def get(self, key: str, default: int) -> int:
            self.lookups.append(key)
            return self.data.get(key, default)

    inventory = CountingInventory(dict(tutorial002.INVENTORY))
    monkeypatch.setattr(tutorial002, "INVENTORY", inventory)

    async with Client(tutorial002.mcp) as client:
        await client.call_tool("order_book", {"title": "Dune"})
        assert inventory.lookups == ["Dune"]
        # Memoization is per call, not per server: the next call looks the title up again.
        await client.call_tool("order_book", {"title": "Dune"})
        assert inventory.lookups == ["Dune", "Dune"]


# The `!!! info` claims the tutorial003 behaviour is transport-independent, so each claim is
# proved on both: mode="legacy" elicits synchronously mid-call (2025-11-25 and earlier), while
# mode="auto" negotiates 2026-07-28, where the question rides a multi-round-trip `tools/call`
# and `Client` drives the retries.
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_an_in_stock_order_asks_no_question(mode: Literal["legacy", "auto"]) -> None:
    """tutorial003: `confirm_backorder` returns directly when stock exists - no round-trip."""

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("an in-stock order must not elicit")

    async with Client(tutorial003.mcp, mode=mode, elicitation_callback=never) as client:
        result = await client.call_tool("order_book", {"title": "Dune"})

    assert result.content == [TextContent(type="text", text="Ordered 'Dune'.")]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize(
    ("confirm", "expected"),
    [
        (True, "Backordered 'Neuromancer'; it ships in 2-3 weeks."),
        (False, "No order placed."),
    ],
)
async def test_an_out_of_stock_order_asks_and_honours_the_answer(
    mode: Literal["legacy", "auto"], confirm: bool, expected: str
) -> None:
    """tutorial003: the resolver elicits, the SDK validates the answer, the tool reads it."""
    asked: list[str] = []

    async def on_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params.message)
        return ElicitResult(action="accept", content={"confirm": confirm})

    async with Client(tutorial003.mcp, mode=mode, elicitation_callback=on_elicit) as client:
        result = await client.call_tool("order_book", {"title": "Neuromancer"})

    assert result.content == [TextContent(type="text", text=expected)]
    assert asked == ["'Neuromancer' is out of stock (2-3 weeks). Order anyway?"]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_declining_an_unwrapped_dependency_aborts_the_call(mode: Literal["legacy", "auto"]) -> None:
    """tutorial003: no answer, no order - the error text on the page is the real one."""

    async def decline(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with Client(tutorial003.mcp, mode=mode, elicitation_callback=decline) as client:
        result = await client.call_tool("order_book", {"title": "Neuromancer"})

    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == (
        "Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline"
    )
