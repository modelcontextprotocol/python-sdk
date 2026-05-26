"""Completion interactions against the low-level Server, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot

from mcp import MCPError, types
from mcp.client.client import Client
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    METHOD_NOT_FOUND,
    CompleteResult,
    Completion,
    ErrorData,
    PromptReference,
    ResourceTemplateReference,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("completion:prompt-arg")
async def test_complete_prompt_argument() -> None:
    """Completing a prompt argument delivers the ref, argument name, and current value to the handler.

    The returned values are filtered by the argument's value, proving the value reached the handler.
    """

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, PromptReference)
        assert params.ref.name == "code_review"
        assert params.argument.name == "language"
        candidates = ["python", "pytorch", "ruby"]
        matches = [candidate for candidate in candidates if candidate.startswith(params.argument.value)]
        return CompleteResult(completion=Completion(values=matches, total=len(matches), has_more=False))

    server = Server("completer", on_completion=completion)

    async with Client(server) as client:
        result = await client.complete(
            PromptReference(name="code_review"), argument={"name": "language", "value": "py"}
        )

    assert result == snapshot(
        CompleteResult(completion=Completion(values=["python", "pytorch"], total=2, has_more=False))
    )


@requirement("completion:resource-template-arg")
async def test_complete_resource_template_variable() -> None:
    """Completing a URI template variable delivers the template URI and variable name to the handler."""

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, ResourceTemplateReference)
        assert params.ref.uri == "github://repos/{owner}/{repo}"
        assert params.argument.name == "owner"
        return CompleteResult(completion=Completion(values=[f"{params.argument.value}contextprotocol"]))

    server = Server("completer", on_completion=completion)

    async with Client(server) as client:
        result = await client.complete(
            ResourceTemplateReference(uri="github://repos/{owner}/{repo}"),
            argument={"name": "owner", "value": "model"},
        )

    assert result == snapshot(CompleteResult(completion=Completion(values=["modelcontextprotocol"])))


@requirement("completion:context-arguments")
async def test_complete_receives_context_arguments() -> None:
    """Previously-resolved arguments passed as completion context reach the handler.

    The returned value is derived from the context, proving it arrived.
    """

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert params.argument.name == "repo"
        assert params.context is not None
        assert params.context.arguments is not None
        return CompleteResult(completion=Completion(values=[f"{params.context.arguments['owner']}/python-sdk"]))

    server = Server("completer", on_completion=completion)

    async with Client(server) as client:
        result = await client.complete(
            ResourceTemplateReference(uri="github://repos/{owner}/{repo}"),
            argument={"name": "repo", "value": ""},
            context_arguments={"owner": "modelcontextprotocol"},
        )

    assert result == snapshot(CompleteResult(completion=Completion(values=["modelcontextprotocol/python-sdk"])))


@requirement("completion:complete:not-supported")
@requirement("protocol:error:method-not-found")
async def test_complete_without_handler_is_method_not_found() -> None:
    """A server with no completion handler advertises no completions capability and rejects the request."""
    server = Server("incomplete")

    async with Client(server) as client:
        assert client.initialize_result.capabilities.completions is None

        with pytest.raises(MCPError) as exc_info:
            await client.complete(PromptReference(name="anything"), argument={"name": "topic", "value": ""})

    assert exc_info.value.error == snapshot(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))
