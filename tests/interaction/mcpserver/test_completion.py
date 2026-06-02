"""Completion behaviour against MCPServer, driven through the public Client API."""

import pytest

from mcp.server.mcpserver import MCPServer
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
    """An MCPServer with a registered completion handler advertises the completions capability; one without does not."""
    with_handler = MCPServer("completer")

    @with_handler.completion()
    async def complete(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        """Registered only so the completions capability is advertised; never called."""
        raise NotImplementedError

    async with connect(with_handler) as client:
        assert client.initialize_result.capabilities.completions == CompletionsCapability()

    async with connect(MCPServer("plain")) as client:
        assert client.initialize_result.capabilities.completions is None
