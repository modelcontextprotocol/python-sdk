"""`docs/advanced/multi-round-trip.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    CallToolResult,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    GetPromptResult,
    InputRequiredResult,
    PromptMessage,
    TextContent,
)

from docs_src.mrtr import tutorial001, tutorial002, tutorial003, tutorial004, tutorial005
from mcp import Client, MCPError
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import InvalidRequestState

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_first_call_returns_an_input_required_result() -> None:
    """tutorial001: a tool that is missing input returns `InputRequiredResult` instead of calling back."""
    async with Client(tutorial001.server) as client:
        result = await client.session.call_tool("provision", {"name": "orders"}, allow_input_required=True)
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


async def test_the_auto_loop_drives_the_call_to_completion() -> None:
    """tutorial003: register `elicitation_callback`, call the tool, get a plain `CallToolResult` back."""
    async with Client(tutorial001.server, elicitation_callback=tutorial003.handle_elicitation) as client:
        result = await client.call_tool("provision", {"name": "orders"})
        assert result == snapshot(
            CallToolResult(content=[TextContent(type="text", text="Provisioned 'orders' in eu-west-1.")])
        )


async def test_the_auto_loop_without_a_callback_raises_mcp_error() -> None:
    """The page's `!!! check`: no `elicitation_callback` means the SDK's stand-in answers with an error."""
    async with Client(tutorial001.server) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("provision", {"name": "orders"})
    assert exc.value.error.code == INVALID_REQUEST
    assert exc.value.error.message == "Elicitation not supported"


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
    """tutorial002: `client.session.call_tool(..., allow_input_required=True)` for callers who own the loop."""
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
            await client.call_tool("provision", {"name": "orders"})
    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Handler returned an invalid result"


def test_fulfil_refuses_a_request_it_cannot_answer() -> None:
    """tutorial002: `fulfil` is the dispatch point. This client only knows how to answer an `ElicitRequest`."""
    request = CreateMessageRequest(params=CreateMessageRequestParams(messages=[], max_tokens=64))
    with pytest.raises(NotImplementedError, match="sampling/createMessage"):
        tutorial002.fulfil(request)


async def test_a_prompt_returns_an_input_required_result_on_the_first_round() -> None:
    """tutorial004: `prompts/get` participates in the same flow — the `@mcp.prompt()` function
    returns the `InputRequiredResult` itself."""
    async with Client(tutorial004.mcp) as client:
        result = await client.session.get_prompt("briefing", allow_input_required=True)
        assert result == snapshot(
            InputRequiredResult(
                result_type="input_required",
                input_requests={
                    "audience": ElicitRequest(
                        method="elicitation/create",
                        params=ElicitRequestFormParams(
                            mode="form",
                            message="Who is the briefing for?",
                            requested_schema={
                                "type": "object",
                                "properties": {"audience": {"type": "string"}},
                                "required": ["audience"],
                            },
                        ),
                    )
                },
            )
        )


async def _answer_audience(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    return ElicitResult(action="accept", content={"audience": "the board"})


async def test_the_prompt_auto_loop_returns_the_final_messages() -> None:
    """tutorial004 + the page's client-side claim: `get_prompt` drives the same loop, so the
    caller sees only the complete `GetPromptResult`."""
    async with Client(tutorial004.mcp, elicitation_callback=_answer_audience) as client:
        result = await client.get_prompt("briefing")
        assert result == snapshot(
            GetPromptResult(
                description="Draft a briefing tuned to its audience.",
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(type="text", text="Write a briefing for the board."),
                    )
                ],
            )
        )


def test_a_custom_codec_round_trips_what_it_sealed() -> None:
    """tutorial005: `unseal(seal(payload))` returns the payload; the token itself is opaque hex."""
    codec = tutorial005.EnvelopeCodec(tutorial005.unwrap_data_key())
    token = codec.seal(b"round-1")
    assert token.startswith(tutorial005.PREFIX)
    assert b"round-1" not in token.encode()
    assert codec.unseal(token) == b"round-1"


def test_a_custom_codec_raises_invalid_request_state_for_any_bad_token() -> None:
    """tutorial005: any token the codec did not mint intact raises `InvalidRequestState`."""
    codec = tutorial005.EnvelopeCodec(tutorial005.unwrap_data_key())
    token = codec.seal(b"round-1")
    with pytest.raises(InvalidRequestState):
        codec.unseal(token + "00")
    with pytest.raises(InvalidRequestState):
        codec.unseal("not-a-token")
