"""Completion interactions against the low-level Server, driven through the public client API."""

import pytest
from inline_snapshot import snapshot

from mcp import McpError
from mcp.server.lowlevel import Server
from mcp.types import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    CompleteResult,
    Completion,
    CompletionArgument,
    CompletionContext,
    ErrorData,
    PromptReference,
    ResourceTemplateReference,
)
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("completion:prompt-arg")
@requirement("completion:result-shape")
async def test_complete_prompt_argument(connect: Connect) -> None:
    """Completing a prompt argument delivers the ref, argument name, and current value to the handler.

    The returned values are filtered by the argument's value, proving the value reached the handler.
    """
    server = Server("completer")

    @server.completion()
    async def completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        assert isinstance(ref, PromptReference)
        assert ref.name == "code_review"
        assert argument.name == "language"
        candidates = ["python", "pytorch", "ruby"]
        matches = [candidate for candidate in candidates if candidate.startswith(argument.value)]
        return Completion(values=matches, total=len(matches), hasMore=False)

    async with connect(server) as client:
        result = await client.complete(
            PromptReference(type="ref/prompt", name="code_review"), argument={"name": "language", "value": "py"}
        )

    assert result == snapshot(
        CompleteResult(completion=Completion(values=["python", "pytorch"], total=2, hasMore=False))
    )


@requirement("completion:resource-template-arg")
async def test_complete_resource_template_variable(connect: Connect) -> None:
    """Completing a URI template variable delivers the template URI and variable name to the handler."""
    server = Server("completer")

    @server.completion()
    async def completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        assert isinstance(ref, ResourceTemplateReference)
        assert ref.uri == "github://repos/{owner}/{repo}"
        assert argument.name == "owner"
        return Completion(values=[f"{argument.value}contextprotocol"])

    async with connect(server) as client:
        result = await client.complete(
            ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
            argument={"name": "owner", "value": "model"},
        )

    assert result == snapshot(CompleteResult(completion=Completion(values=["modelcontextprotocol"])))


@requirement("completion:context-arguments")
async def test_complete_receives_context_arguments(connect: Connect) -> None:
    """Previously-resolved arguments passed as completion context reach the handler.

    The returned value is derived from the context, proving it arrived.
    """
    server = Server("completer")

    @server.completion()
    async def completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        assert argument.name == "repo"
        assert context is not None
        assert context.arguments is not None
        return Completion(values=[f"{context.arguments['owner']}/python-sdk"])

    async with connect(server) as client:
        result = await client.complete(
            ResourceTemplateReference(type="ref/resource", uri="github://repos/{owner}/{repo}"),
            argument={"name": "repo", "value": ""},
            context_arguments={"owner": "modelcontextprotocol"},
        )

    assert result == snapshot(CompleteResult(completion=Completion(values=["modelcontextprotocol/python-sdk"])))


@requirement("completion:error:invalid-ref")
async def test_completion_against_an_unknown_ref_is_rejected_with_invalid_params(connect: Connect) -> None:
    """completion/complete with a ref naming an unknown prompt is answered with -32602 Invalid params.

    The lowlevel server does not validate refs itself (it has no prompt/template registry to check
    against); rejecting an unknown ref is the handler's job, and this test pins the spec-recommended
    way to do it.
    """
    server = Server("completer")

    @server.completion()
    async def completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        assert isinstance(ref, PromptReference)
        raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Unknown prompt: {ref.name!r}"))

    async with connect(server) as client:
        with pytest.raises(McpError) as exc_info:
            await client.complete(PromptReference(type="ref/prompt", name="ghost"), argument={"name": "x", "value": ""})

    assert exc_info.value.error.code == INVALID_PARAMS


@requirement("completion:complete:not-supported")
@requirement("protocol:error:method-not-found")
async def test_complete_without_handler_is_method_not_found(connect: Connect) -> None:
    """A server with no completion handler advertises no completions capability and rejects the request."""
    server = Server("incomplete")

    async with connect(server) as client:
        capabilities = client.get_server_capabilities()
        assert capabilities is not None
        assert capabilities.completions is None

        with pytest.raises(McpError) as exc_info:
            await client.complete(
                PromptReference(type="ref/prompt", name="anything"), argument={"name": "topic", "value": ""}
            )

    assert exc_info.value.error == snapshot(ErrorData(code=METHOD_NOT_FOUND, message="Method not found"))
