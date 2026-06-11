"""Completion behaviour against FastMCP, driven through the public client API."""

import pytest

from mcp.server.fastmcp import FastMCP
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    CompletionsCapability,
    PromptReference,
    ResourceTemplateReference,
)
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:completion:capability-auto")
async def test_completion_capability_is_advertised_only_when_a_handler_is_registered(connect: Connect) -> None:
    """A FastMCP with a registered completion handler advertises the completions capability; one without does not."""
    with_handler = FastMCP("completer")

    @with_handler.completion()
    async def complete(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        """Registered only so the completions capability is advertised; never called."""
        raise NotImplementedError

    async with connect(with_handler) as client:
        capabilities = client.get_server_capabilities()
        assert capabilities is not None
        assert capabilities.completions == CompletionsCapability()

    async with connect(FastMCP("plain")) as client:
        capabilities = client.get_server_capabilities()
        assert capabilities is not None
        assert capabilities.completions is None
