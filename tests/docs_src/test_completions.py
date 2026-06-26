"""`docs/tutorial/completions.md`: every claim the page makes, proved against the real SDK."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    Completion,
    CompletionContext,
    CompletionsCapability,
    ErrorData,
    PromptReference,
    ResourceTemplateReference,
)

from docs_src.completions import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]

TEMPLATE_REF = ResourceTemplateReference(uri="github://repos/{owner}/{repo}")
PROMPT_REF = PromptReference(name="review_code")


async def test_a_server_with_no_handler_has_no_completions_capability() -> None:
    """tutorial001: there is something worth completing, but no handler and no advertised capability."""
    async with Client(tutorial001.mcp) as client:
        (template,) = (await client.list_resource_templates()).resource_templates
        assert template.uri_template == "github://repos/{owner}/{repo}"
        (prompt,) = (await client.list_prompts()).prompts
        assert prompt.name == "review_code"
        assert client.server_capabilities.completions is None


async def test_completing_without_a_handler_is_method_not_found() -> None:
    """tutorial001: nothing handles `completion/complete`, so the request is a JSON-RPC error."""
    async with Client(tutorial001.mcp) as client:
        with pytest.raises(MCPError) as excinfo:
            await client.complete(ref=PROMPT_REF, argument={"name": "language", "value": "py"})
        assert excinfo.value.error == ErrorData(code=-32601, message="Method not found", data="completion/complete")


async def test_registering_the_handler_advertises_the_capability() -> None:
    """tutorial002: `@mcp.completion()` is the whole declaration; the capability is derived from it."""
    async with Client(tutorial002.mcp) as client:
        assert client.server_capabilities.completions == CompletionsCapability()


async def test_prompt_argument_completion_filters_on_the_typed_prefix() -> None:
    """tutorial002: the handler returns the languages that start with `argument.value`."""
    async with Client(tutorial002.mcp) as client:
        result = await client.complete(ref=PROMPT_REF, argument={"name": "language", "value": "py"})
        assert result.completion == snapshot(Completion(values=["python"]))


async def test_empty_value_returns_every_suggestion() -> None:
    """tutorial002: an empty prefix matches everything, so the client gets the whole list."""
    async with Client(tutorial002.mcp) as client:
        result = await client.complete(ref=PROMPT_REF, argument={"name": "language", "value": ""})
        assert result.completion.values == ["go", "javascript", "python", "rust", "typescript"]


async def test_returning_none_is_an_empty_list_not_an_error() -> None:
    """tutorial002: an argument the handler does not recognise produces `values=[]`, never a failure."""
    async with Client(tutorial002.mcp) as client:
        result = await client.complete(ref=PROMPT_REF, argument={"name": "code", "value": "x"})
        assert result.completion == snapshot(Completion(values=[]))
        result = await client.complete(ref=TEMPLATE_REF, argument={"name": "repo", "value": ""})
        assert result.completion.values == []


async def test_context_arguments_resolve_a_dependent_parameter() -> None:
    """tutorial003: the already-resolved `owner` arrives in `context.arguments` and picks the repo list."""
    async with Client(tutorial003.mcp) as client:
        result = await client.complete(
            ref=TEMPLATE_REF,
            argument={"name": "repo", "value": ""},
            context_arguments={"owner": "modelcontextprotocol"},
        )
        assert result.completion == snapshot(Completion(values=["python-sdk", "typescript-sdk", "inspector"]))


async def test_the_typed_prefix_still_filters_a_dependent_parameter() -> None:
    """tutorial003: `argument.value` narrows the owner's repos exactly as it narrows a prompt argument."""
    async with Client(tutorial003.mcp) as client:
        result = await client.complete(
            ref=TEMPLATE_REF,
            argument={"name": "repo", "value": "py"},
            context_arguments={"owner": "modelcontextprotocol"},
        )
        assert result.completion.values == ["python-sdk"]


def test_context_arguments_is_optional() -> None:
    """tutorial003: `context.arguments` is `dict[str, str] | None`; the handler's `None` guard is required."""
    assert CompletionContext.model_fields["arguments"].annotation == (dict[str, str] | None)
    assert CompletionContext().arguments is None


async def test_no_context_means_no_suggestions() -> None:
    """tutorial003: without a resolved `owner` (or with an unknown one) the handler has nothing to offer."""
    async with Client(tutorial003.mcp) as client:
        result = await client.complete(ref=TEMPLATE_REF, argument={"name": "repo", "value": ""})
        assert result.completion.values == []
        result = await client.complete(
            ref=TEMPLATE_REF,
            argument={"name": "repo", "value": ""},
            context_arguments={"owner": "nobody"},
        )
        assert result.completion.values == []


async def test_the_prompt_branch_is_untouched_by_the_new_one() -> None:
    """tutorial003: adding the resource-template branch leaves prompt-argument completion as it was."""
    async with Client(tutorial003.mcp) as client:
        result = await client.complete(ref=PROMPT_REF, argument={"name": "language", "value": "type"})
        assert result.completion.values == ["typescript"]
