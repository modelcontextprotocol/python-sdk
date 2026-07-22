"""Prompt interactions against MCPServer, driven through the public Client API."""

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    ErrorData,
    GetPromptResult,
    ListPromptsResult,
    Prompt,
    PromptArgument,
    PromptMessage,
    TextContent,
)

from mcp import MCPError
from mcp.server.mcpserver import MCPServer
from tests._stamp import unstamped
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


@requirement("mcpserver:prompt:decorated")
async def test_list_prompts_derives_arguments_from_signature(connect: Connect) -> None:
    """A decorated prompt is listed with arguments derived from the function signature.

    Parameters without a default are required; the description comes from the docstring.
    """
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def code_review(code: str, style_guide: str = "pep8") -> str:
        """Review a piece of code."""
        raise NotImplementedError  # registered for listing only; never rendered

    async with connect(mcp) as client:
        result = await client.list_prompts()

    assert unstamped(result) == snapshot(
        ListPromptsResult(
            prompts=[
                Prompt(
                    name="code_review",
                    description="Review a piece of code.",
                    arguments=[
                        PromptArgument(name="code", required=True),
                        PromptArgument(name="style_guide", required=False),
                    ],
                )
            ]
        )
    )


@requirement("mcpserver:prompt:decorated")
async def test_get_prompt_renders_function_return(connect: Connect) -> None:
    """The decorated function's string return value is rendered as a single user message."""
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def greet(name: str) -> str:
        """A personalised greeting."""
        return f"Say hello to {name}."

    async with connect(mcp) as client:
        result = await client.get_prompt("greet", {"name": "Ada"})

    assert unstamped(result) == snapshot(
        GetPromptResult(
            description="A personalised greeting.",
            messages=[PromptMessage(role="user", content=TextContent(text="Say hello to Ada."))],
        )
    )


@requirement("mcpserver:prompt:unknown-name")
async def test_get_unknown_prompt_is_error(connect: Connect) -> None:
    """Getting a prompt name that was never registered fails with a JSON-RPC error.

    The spec reserves -32602 for this case; the SDK reports code 0 (see the divergence note on
    the requirement).
    """
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def greet(name: str) -> str:
        """A registered prompt; the test requests a different name."""
        raise NotImplementedError

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("nope")

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="Unknown prompt: nope"))


@requirement("prompts:get:missing-required-args")
async def test_get_prompt_with_a_missing_required_argument_is_an_error(connect: Connect) -> None:
    """Getting a prompt without one of its required arguments fails with a JSON-RPC error.

    The missing argument is detected before the prompt function is called, but the spec's -32602
    Invalid params is reported as error code 0 with the bare exception text (see the divergence
    note on the requirement).
    """
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def greet(name: str) -> str:
        """A registered prompt; validation rejects the call before the function runs."""
        raise NotImplementedError

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("greet")

    assert exc_info.value.error == snapshot(ErrorData(code=0, message="Missing required arguments: {'name'}"))


@requirement("mcpserver:prompt:args-validation")
async def test_get_prompt_with_a_wrong_type_argument_is_rejected_before_the_function_runs(connect: Connect) -> None:
    """An argument that fails the function signature's type validation is rejected before the function runs.

    The decorated function is wrapped in pydantic's validate_call, so a value that cannot be
    coerced to the parameter's annotation fails before the body executes. The function body
    raises NotImplementedError to prove it never ran. The error is wrapped in the SDK's stable
    rendering-error prefix; the body of the message is raw pydantic output and is not asserted.
    """
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def repeat(phrase: str, count: int) -> str:
        """A registered prompt; type validation rejects the call before the function runs."""
        raise NotImplementedError

    async with connect(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.get_prompt("repeat", {"phrase": "hi", "count": "many"})

    assert exc_info.value.error.code == 0
    assert exc_info.value.error.message.startswith("Error rendering prompt repeat: 1 validation error")


@requirement("mcpserver:prompt:optional-args")
async def test_get_prompt_with_an_optional_argument_omitted_uses_the_default(connect: Connect) -> None:
    """A prompt rendered without one of its optional arguments uses that parameter's default value."""
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def review(code: str, style: str = "pep8") -> str:
        """Review a snippet of code against a style guide."""
        return f"Review {code} per {style}."

    async with connect(mcp) as client:
        result = await client.get_prompt("review", {"code": "x = 1"})

    assert unstamped(result) == snapshot(
        GetPromptResult(
            description="Review a snippet of code against a style guide.",
            messages=[PromptMessage(role="user", content=TextContent(text="Review x = 1 per pep8."))],
        )
    )


@requirement("mcpserver:prompt:duplicate-name")
async def test_registering_a_duplicate_prompt_name_warns_and_keeps_the_first(connect: Connect) -> None:
    """Registering a second prompt with an already-used name keeps the first registration.

    The intended behaviour is rejection at registration time; MCPServer instead logs a warning
    and discards the second registration (see the divergence note on the requirement). The
    second function is registered via the decorator with an explicit name so the test does not
    redefine the same function name in this scope.
    """
    mcp = MCPServer("prompter")

    @mcp.prompt()
    def greet() -> str:
        """The first registration; this is the one that wins."""
        return "first"

    @mcp.prompt(name="greet")
    def greet_second() -> str:
        """Registered with a duplicate name; the registration is discarded so this never runs."""
        raise NotImplementedError

    async with connect(mcp) as client:
        listed = await client.list_prompts()
        result = await client.get_prompt("greet")

    assert [prompt.name for prompt in listed.prompts] == ["greet"]
    assert unstamped(result) == snapshot(
        GetPromptResult(
            description="The first registration; this is the one that wins.",
            messages=[PromptMessage(role="user", content=TextContent(text="first"))],
        )
    )
