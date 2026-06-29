"""Completion interactions against the low-level Server, driven through the public Client API."""

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    CompleteResult,
    Completion,
    ErrorData,
    PromptReference,
    ResourceTemplateReference,
)

from mcp import MCPError
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("completion:prompt-arg")
@requirement("completion:result-shape")
async def test_complete_prompt_argument(connect: Connect) -> None:
    """Returned values are filtered by the argument's value, proving it reached the handler."""

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, PromptReference)
        assert params.ref.name == "code_review"
        assert params.argument.name == "language"
        candidates = ["python", "pytorch", "ruby"]
        matches = [candidate for candidate in candidates if candidate.startswith(params.argument.value)]
        return CompleteResult(completion=Completion(values=matches, total=len(matches), has_more=False))

    server = Server("completer", on_completion=completion)

    async with connect(server) as client:
        result = await client.complete(
            PromptReference(name="code_review"), argument={"name": "language", "value": "py"}
        )

    assert result == snapshot(
        CompleteResult(completion=Completion(values=["python", "pytorch"], total=2, has_more=False))
    )


@requirement("completion:resource-template-arg")
async def test_complete_resource_template_variable(connect: Connect) -> None:
    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, ResourceTemplateReference)
        assert params.ref.uri == "github://repos/{owner}/{repo}"
        assert params.argument.name == "owner"
        return CompleteResult(completion=Completion(values=[f"{params.argument.value}contextprotocol"]))

    server = Server("completer", on_completion=completion)

    async with connect(server) as client:
        result = await client.complete(
            ResourceTemplateReference(uri="github://repos/{owner}/{repo}"),
            argument={"name": "owner", "value": "model"},
        )

    assert result == snapshot(CompleteResult(completion=Completion(values=["modelcontextprotocol"])))


@requirement("completion:context-arguments")
async def test_complete_receives_context_arguments(connect: Connect) -> None:
    """The returned value derives from the context arguments, proving they reached the handler."""

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert params.argument.name == "repo"
        assert params.context is not None
        assert params.context.arguments is not None
        return CompleteResult(completion=Completion(values=[f"{params.context.arguments['owner']}/python-sdk"]))

    server = Server("completer", on_completion=completion)

    async with connect(server) as client:
        result = await client.complete(
            ResourceTemplateReference(uri="github://repos/{owner}/{repo}"),
            argument={"name": "repo", "value": ""},
            context_arguments={"owner": "modelcontextprotocol"},
        )

    assert result == snapshot(CompleteResult(completion=Completion(values=["modelcontextprotocol/python-sdk"])))


@requirement("completion:error:invalid-ref")
async def test_completion_against_an_unknown_ref_is_rejected_with_invalid_params(connect: Connect) -> None:
    """The lowlevel server has no prompt/template registry; rejecting an unknown ref is the handler's job."""

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> CompleteResult:
        assert isinstance(params.ref, PromptReference)
        raise MCPError(code=INVALID_PARAMS, message=f"Unknown prompt: {params.ref.name!r}")

    server = Server("completer", on_completion=completion)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.complete(PromptReference(name="ghost"), argument={"name": "x", "value": ""})

    assert exc_info.value.error.code == INVALID_PARAMS


@requirement("completion:complete:not-supported")
@requirement("protocol:error:method-not-found")
async def test_complete_without_handler_is_method_not_found(connect: Connect) -> None:
    server = Server("incomplete")

    async with connect(server) as client:
        assert client.server_capabilities.completions is None

        with pytest.raises(MCPError) as exc_info:
            await client.complete(PromptReference(name="anything"), argument={"name": "topic", "value": ""})

    assert exc_info.value.error == snapshot(
        ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="completion/complete")
    )
