"""`docs/advanced/multi-round-trip.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    CallToolResult,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    TextContent,
)

from docs_src.mrtr import tutorial001, tutorial002
from mcp import Client, MCPError

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_first_call_returns_an_input_required_result() -> None:
    """tutorial001: a tool that is missing input returns `InputRequiredResult` instead of calling back."""
    async with Client(tutorial001.server) as client:
        result = await client.call_tool("provision", {"name": "orders"}, allow_input_required=True)
        assert result == snapshot(
            InputRequiredResult(
                result_type="input_required",
                input_requests={
                    "region": ElicitRequest(
                        method="elicitation/create",
                        params=ElicitRequestFormParams(
                            mode="form",
                            message="Which region should the database live in?",
                            requested_schema={
                                "type": "object",
                                "properties": {"region": {"type": "string"}},
                                "required": ["region"],
                            },
                        ),
                    )
                },
                request_state="provision-v1",
            )
        )


async def test_call_tool_raises_without_the_opt_in() -> None:
    """The page's `!!! check`: `allow_input_required` defaults to `False` and the result is a hard error."""
    async with Client(tutorial001.server) as client:
        with pytest.raises(RuntimeError) as exc:
            await client.call_tool("provision", {"name": "orders"})
    assert str(exc.value) == (
        "Server returned InputRequiredResult; pass allow_input_required=True to receive it "
        "and retry call_tool(..., input_responses=..., request_state=result.request_state)."
    )


async def test_retry_with_input_responses_and_request_state_completes_the_call() -> None:
    """tutorial001: the retry carries `input_responses` keyed like `input_requests` plus the echoed token."""
    async with Client(tutorial001.server) as client:
        result = await client.call_tool(
            "provision",
            {"name": "orders"},
            input_responses={"region": ElicitResult(action="accept", content={"region": "eu-west-1"})},
            request_state="provision-v1",
        )
        assert result == snapshot(
            CallToolResult(content=[TextContent(type="text", text="Provisioned 'orders' in eu-west-1.")])
        )


async def test_the_manual_loop_drives_the_call_to_completion() -> None:
    """tutorial002: `while isinstance(result, InputRequiredResult)` is the whole client API, and it terminates."""
    async with Client(tutorial001.server) as client:
        result = await tutorial002.provision(client, "billing")
        assert result == snapshot(
            CallToolResult(content=[TextContent(type="text", text="Provisioned 'billing' in eu-west-1.")])
        )


async def test_the_in_memory_client_negotiates_2026_07_28() -> None:
    """`InputRequiredResult` only exists at 2026-07-28; `Client(server)` lands there without being asked."""
    async with Client(tutorial001.server) as client:
        assert client.protocol_version == "2026-07-28"


async def test_a_pre_2026_session_has_nowhere_to_put_the_result() -> None:
    """The page's `!!! warning`: on a legacy session the runner cannot serialize an `InputRequiredResult`."""
    async with Client(tutorial001.server, mode="legacy") as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("provision", {"name": "orders"}, allow_input_required=True)
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Handler returned an invalid result"


def test_fulfil_refuses_a_request_it_cannot_answer() -> None:
    """tutorial002: `fulfil` is the dispatch point. This client only knows how to answer an `ElicitRequest`."""
    request = CreateMessageRequest(params=CreateMessageRequestParams(messages=[], max_tokens=64))
    with pytest.raises(NotImplementedError, match="sampling/createMessage"):
        tutorial002.fulfil(request)
