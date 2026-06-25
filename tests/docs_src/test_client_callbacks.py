"""`docs/client/callbacks.md` — every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_REQUEST,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    ListRootsResult,
    Root,
    SamplingMessage,
    TextContent,
)
from pydantic import FileUrl

from docs_src.client_callbacks import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client, MCPError
from mcp.client import ClientRequestContext

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_callback_answers_the_servers_question() -> None:
    """tutorial001+002: the server's `ctx.elicit` is resolved by the client's `elicitation_callback`."""
    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=tutorial002.handle_elicitation) as client:
        result = await client.call_tool("issue_card")
    assert not result.is_error
    assert result.content == [TextContent(type="text", text="Card issued to Ada Lovelace.")]


async def test_the_callback_receives_the_servers_question_as_form_params() -> None:
    """tutorial002: the callback gets `ElicitRequestFormParams` — the message and the requested schema."""
    received: list[ElicitRequestParams] = []

    async def recording(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        received.append(params)
        return await tutorial002.handle_elicitation(context, params)

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=recording) as client:
        await client.call_tool("issue_card")
    (params,) = received
    assert isinstance(params, ElicitRequestFormParams)
    assert params.mode == "form"
    assert params.message == "What name should go on the card?"
    assert params.requested_schema == snapshot(
        {
            "properties": {"name": {"title": "Name", "type": "string"}},
            "required": ["name"],
            "title": "CardHolder",
            "type": "object",
        }
    )


async def test_returning_error_data_refuses_the_request_and_fails_the_call() -> None:
    """The callback's only other return type: `ErrorData` refuses the request and fails the whole call."""

    async def refuse(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult | ErrorData:
        return ErrorData(code=INVALID_REQUEST, message="No forms here.")

    async with Client(tutorial001.mcp, mode="legacy", elicitation_callback=refuse) as client:
        with pytest.raises(MCPError, match="No forms here") as exc_info:
            await client.call_tool("issue_card")
    assert exc_info.value.error.code == INVALID_REQUEST


async def test_without_the_callback_the_servers_request_is_refused() -> None:
    """The `!!! check`: no `elicitation_callback` means the SDK answers with an error and the call fails."""
    async with Client(tutorial001.mcp, mode="legacy") as client:
        with pytest.raises(MCPError, match="Elicitation not supported") as exc_info:
            await client.call_tool("issue_card")
    assert exc_info.value.error.code == INVALID_REQUEST


async def test_registering_the_callback_declares_the_capability() -> None:
    """tutorial003: `elicitation_callback` alone advertises exactly the `elicitation` capability."""
    async with Client(tutorial003.mcp, mode="legacy", elicitation_callback=tutorial002.handle_elicitation) as client:
        result = await client.call_tool("client_features")
    assert result.structured_content == {"result": ["elicitation"]}


async def test_no_callbacks_means_no_capabilities() -> None:
    """tutorial003: a client constructed without callbacks declares nothing."""
    async with Client(tutorial003.mcp, mode="legacy") as client:
        result = await client.call_tool("client_features")
    assert result.structured_content == {"result": []}


async def test_each_callback_declares_its_own_capability() -> None:
    """The page's table: the elicitation, sampling, and roots callbacks each declare their capability."""
    async with Client(
        tutorial003.mcp,
        mode="legacy",
        elicitation_callback=tutorial002.handle_elicitation,
        sampling_callback=tutorial004.handle_sampling,
        list_roots_callback=tutorial004.handle_list_roots,
    ) as client:
        result = await client.call_tool("client_features")
    assert result.structured_content == {"result": ["elicitation", "sampling", "roots"]}


async def test_the_modern_in_memory_path_has_no_back_channel() -> None:
    """The `!!! info`: under the default mode the negotiated path has no back-channel for `elicitation/create`."""
    async with Client(tutorial001.mcp, elicitation_callback=tutorial002.handle_elicitation) as client:
        with pytest.raises(MCPError, match="Method not found"):
            await client.call_tool("issue_card")


async def test_the_deprecated_callbacks_return_what_the_page_says() -> None:
    """tutorial004: the sampling and roots callbacks produce the result types the page names."""
    async with Client(tutorial003.mcp, mode="legacy") as client:
        context = ClientRequestContext(session=client.session, request_id=1)
        params = CreateMessageRequestParams(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text="6 * 7?"))],
            max_tokens=16,
        )
        assert await tutorial004.handle_sampling(context, params) == snapshot(
            CreateMessageResult(
                role="assistant", content=TextContent(type="text", text="The answer is 42."), model="my-llm"
            )
        )
        assert await tutorial004.handle_list_roots(context) == snapshot(
            ListRootsResult(roots=[Root(uri=FileUrl("file:///home/ada/notebooks"), name="notebooks")])
        )
