"""Prove the refund amount is schema-hidden, resolvers memoize per call, and decline semantics differ per consumer."""

import mcp_types as types

from mcp.client import Client, ClientRequestContext
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    counts = {"scope": 0, "restock": 0}
    answers: dict[str, dict[str, str | int | float | bool | list[str] | None]] = {
        "scope": {"full": True},
        "restock": {"restock": True},
    }
    declines: set[str] = set()

    async def on_elicit(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
        assert isinstance(params, types.ElicitRequestFormParams)
        topic = "scope" if "full" in params.requested_schema["properties"] else "restock"
        counts[topic] += 1
        if topic in declines:
            return types.ElicitResult(action="decline")
        return types.ElicitResult(action="accept", content=answers[topic])

    async with Client(target, mode=mode, elicitation_callback=on_elicit) as client:
        # The model-facing contract is order_id + reason only; cents and restock are resolver-filled.
        listed = await client.list_tools()
        (tool,) = listed.tools
        assert set(tool.input_schema["properties"]) == {"order_id", "reason"}, tool.input_schema
        assert set(tool.input_schema.get("required", ())) == {"order_id", "reason"}, tool.input_schema

        # One digital line: scope auto-fills (full), restock auto-fills (False) — zero round-trips.
        receipt = await client.call_tool("refund_order", {"order_id": "ORD-7001", "reason": "download corrupted"})
        assert receipt.structured_content == {
            "order_id": "ORD-7001",
            "refunded_cents": 1500,
            "restocked": False,
            "reason": "download corrupted",
        }, receipt.structured_content
        assert counts == {"scope": 0, "restock": 0}, counts

        # Scope fires exactly ONCE per call even though refund_amount and ask_restock both consume it.
        # ask_restock needs scope's ANSWER, so at 2026 the two land in successive rounds — era-independent.
        receipt = await client.call_tool("refund_order", {"order_id": "ORD-7002", "reason": "arrived broken"})
        assert receipt.structured_content == {
            "order_id": "ORD-7002",
            "refunded_cents": 4800,
            "restocked": True,
            "reason": "arrived broken",
        }, receipt.structured_content
        assert counts == {"scope": 1, "restock": 1}, counts

        # Declining restock still refunds: the tool takes `restock` as an ElicitationResult union and
        # skips the restock on decline. Scope is asked again — deduped per call, not per connection.
        declines.add("restock")
        answers["scope"] = {"full": False, "sku": "canvas-tote"}
        receipt = await client.call_tool("refund_order", {"order_id": "ORD-7002", "reason": "wrong colour"})
        assert receipt.structured_content == {
            "order_id": "ORD-7002",
            "refunded_cents": 2400,
            "restocked": False,
            "reason": "wrong colour",
        }, receipt.structured_content
        assert counts == {"scope": 2, "restock": 2}, counts
        declines.clear()

        # An elicited SKU is human-typed, so the server validates it against the order before computing money.
        answers["scope"] = {"full": False, "sku": "mystery-hat"}
        result = await client.call_tool("refund_order", {"order_id": "ORD-7002", "reason": "lost parcel"})
        assert result.is_error, result
        assert isinstance(result.content[0], types.TextContent)
        assert "order has no item 'mystery-hat'" in result.content[0].text, result.content[0].text

        # Declining scope aborts the whole call: both resolvers consume scope unwrapped, so whichever
        # resolves first aborts and ask_restock never runs.
        declines.add("scope")
        restock_before = counts["restock"]
        result = await client.call_tool("refund_order", {"order_id": "ORD-7002", "reason": "changed mind"})
        assert result.is_error, result
        assert isinstance(result.content[0], types.TextContent)
        assert "Resolver for parameter 'scope' could not resolve: elicitation was decline" in result.content[0].text, (
            result.content[0].text
        )
        assert counts["restock"] == restock_before, counts
        declines.clear()

        # A ToolError raised inside a resolver surfaces exactly like one from the tool body.
        result = await client.call_tool("refund_order", {"order_id": "ORD-9999", "reason": "typo"})
        assert result.is_error, result
        assert isinstance(result.content[0], types.TextContent)
        assert "unknown order 'ORD-9999'" in result.content[0].text, result.content[0].text

        # Final tally: scope fired in legs 2-5, restock only in the two calls that reached it.
        assert counts == {"scope": 4, "restock": 2}, counts


if __name__ == "__main__":
    run_client(main)
