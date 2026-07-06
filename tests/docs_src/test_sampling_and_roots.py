"""`docs/handlers/sampling-and-roots.md`: every claim the page makes, proved against the real SDK."""

from typing import Literal

import pytest
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    CreateMessageRequestParams,
    CreateMessageResult,
    ListRootsResult,
    Root,
    TextContent,
)
from pydantic import FileUrl

from docs_src.sampling_and_roots import tutorial001, tutorial002
from mcp import Client
from mcp.client import ClientRequestContext
from mcp.shared.exceptions import MCPError

pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_a_sampling_dependency_receives_the_clients_completion(mode: Literal["legacy", "auto"]) -> None:
    """tutorial001: `draft_blurb` runs through the client's model on both protocol versions."""
    prompts: list[str] = []

    async def sampler(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
        content = params.messages[0].content
        assert isinstance(content, TextContent)
        prompts.append(content.text)
        return CreateMessageResult(
            role="assistant", content=TextContent(type="text", text="A desert planet holds the key."), model="m"
        )

    async with Client(tutorial001.mcp, mode=mode, sampling_callback=sampler) as client:
        result = await client.call_tool("blurb", {"title": "Dune"})

    assert result.content == [TextContent(type="text", text="A desert planet holds the key.")]
    assert prompts == ["Write a one-sentence blurb for the book 'Dune'."]


@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_a_roots_dependency_receives_the_clients_folders(mode: Literal["legacy", "auto"]) -> None:
    """tutorial002: `workspace_roots` fetches the client's roots list."""

    async def client_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=FileUrl("file:///workspace/catalog"), name="catalog")])

    async with Client(tutorial002.mcp, mode=mode, list_roots_callback=client_roots) as client:
        result = await client.call_tool("catalog_folder", {})

    assert result.content == [TextContent(type="text", text="file:///workspace/catalog")]


async def test_an_undeclared_capability_fails_before_a_request_is_sent() -> None:
    """The page's gate claim: no `sampling` capability means a -32021 protocol error."""
    async with Client(tutorial001.mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("blurb", {"title": "Dune"})
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
