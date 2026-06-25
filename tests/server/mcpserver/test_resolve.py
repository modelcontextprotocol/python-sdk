"""Tests for resolver dependency injection (MRTR) on MCPServer tools."""

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    Context,
    DeclinedElicitation,
    Elicit,
    MCPServer,
    Resolve,
)
from mcp.server.mcpserver.exceptions import InvalidSignature
from mcp.server.mcpserver.resolve import find_resolved_parameters
from mcp.server.mcpserver.tools.base import Tool
from mcp.types import ElicitRequestParams, ElicitResult, TextContent


class Login(BaseModel):
    username: str


class Confirm(BaseModel):
    ok: bool


def _accept(content: dict[str, str | int | float | bool | list[str] | None]):
    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content=content)

    return callback


async def _decline(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    return ElicitResult(action="decline")


async def _text(client: Client, tool: str, args: dict[str, object]) -> str:
    result = await client.call_tool(tool, args)
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    return result.content[0].text


@pytest.mark.anyio
async def test_resolver_returns_value_directly_without_eliciting():
    mcp = MCPServer(name="Direct")

    async def login(ctx: Context) -> Login | Elicit[Login]:
        username = (ctx.headers or {}).get("x-github-user")
        if username:  # pragma: no cover - no headers on in-memory transport
            return Login(username=username)
        return Login(username="from-resolver")

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(login)]) -> str:
        return login.username

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "whoami", {}) == "from-resolver"


@pytest.mark.anyio
async def test_resolver_elicits_and_injects_unwrapped_model_on_accept():
    mcp = MCPServer(name="Accept")

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(login)]) -> str:
        return login.username

    async with Client(mcp, mode="legacy", elicitation_callback=_accept({"username": "octocat"})) as client:
        assert await _text(client, "whoami", {}) == "octocat"


@pytest.mark.anyio
async def test_consumer_receives_result_union_and_branches():
    mcp = MCPServer(name="Union")

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    @mcp.tool()
    async def whoami(
        login: Annotated[AcceptedElicitation[Login] | DeclinedElicitation | CancelledElicitation, Resolve(login)],
    ) -> str:
        match login:
            case AcceptedElicitation(data=data):
                return f"hi {data.username}"
            case _:  # pragma: no cover - accepted in this test
                return "no username"

    async with Client(mcp, mode="legacy", elicitation_callback=_accept({"username": "octocat"})) as client:
        assert await _text(client, "whoami", {}) == "hi octocat"


@pytest.mark.anyio
async def test_decline_reaches_union_consumer_without_aborting():
    mcp = MCPServer(name="UnionDecline")

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    @mcp.tool()
    async def whoami(
        login: Annotated[AcceptedElicitation[Login] | DeclinedElicitation | CancelledElicitation, Resolve(login)],
    ) -> str:
        if isinstance(login, DeclinedElicitation):
            return "declined gracefully"
        raise NotImplementedError

    async with Client(mcp, mode="legacy", elicitation_callback=_decline) as client:
        assert await _text(client, "whoami", {}) == "declined gracefully"


@pytest.mark.anyio
async def test_decline_aborts_when_consumer_wants_unwrapped():
    mcp = MCPServer(name="UnwrappedDecline")

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(login)]) -> str:
        raise NotImplementedError  # pragma: no cover - never reached

    async with Client(mcp, mode="legacy", elicitation_callback=_decline) as client:
        result = await client.call_tool("whoami", {})
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        assert "decline" in result.content[0].text


@pytest.mark.anyio
async def test_nested_resolver_sees_dependency_and_tool_args():
    mcp = MCPServer(name="Nested")

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    async def confirm(repo: str, login: Annotated[Login, Resolve(login)]) -> Elicit[Confirm]:
        return Elicit(f"Star {repo} as {login.username}?", Confirm)

    @mcp.tool()
    async def star_repo(
        repo: str,
        login: Annotated[Login, Resolve(login)],
        confirm: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        if confirm.ok:
            return f"starred {repo} as {login.username}"
        raise NotImplementedError

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        if "username" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        assert "Star modelcontextprotocol/python-sdk as octocat?" in params.message
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, mode="legacy", elicitation_callback=callback) as client:
        text = await _text(client, "star_repo", {"repo": "modelcontextprotocol/python-sdk"})
        assert text == "starred modelcontextprotocol/python-sdk as octocat"


@pytest.mark.anyio
async def test_resolver_runs_once_for_two_consumers():
    mcp = MCPServer(name="ExactlyOnce")
    elicit_count = 0

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    async def confirm(login: Annotated[Login, Resolve(login)]) -> Elicit[Confirm]:
        return Elicit(f"As {login.username}?", Confirm)

    @mcp.tool()
    async def star_repo(
        login: Annotated[Login, Resolve(login)],
        confirm: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        return f"{login.username}:{confirm.ok}"

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        nonlocal elicit_count
        if "username" in params.message:
            elicit_count += 1
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, mode="legacy", elicitation_callback=callback) as client:
        assert await _text(client, "star_repo", {}) == "octocat:True"
    assert elicit_count == 1


@pytest.mark.anyio
async def test_sync_resolver():
    mcp = MCPServer(name="Sync")

    def login(ctx: Context) -> Login:
        return Login(username="sync-user")

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(login)]) -> str:
        return login.username

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "whoami", {}) == "sync-user"


def test_resolved_params_absent_from_input_schema():
    async def login(ctx: Context) -> Login:
        return Login(username="x")  # pragma: no cover - only the schema is inspected

    async def tool(
        repo: Annotated[str, Field(description="repo name")],
        login: Annotated[Login, Resolve(login)],
    ) -> str:
        return repo  # pragma: no cover - only the schema is inspected

    built = Tool.from_function(tool)
    properties = built.parameters["properties"]
    assert "repo" in properties
    assert "login" not in properties


def test_cycle_detection_raises_at_registration():
    async def a(dep: Login) -> Login:
        return dep  # pragma: no cover

    async def b(dep: Login) -> Login:
        return dep  # pragma: no cover

    # Close the loop after both exist: a depends on b, b depends on a.
    a.__annotations__["dep"] = Annotated[Login, Resolve(b)]
    b.__annotations__["dep"] = Annotated[Login, Resolve(a)]

    async def tool(value: Annotated[Login, Resolve(a)]) -> str:
        return value.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="cyclic"):
        Tool.from_function(tool)


def test_find_resolved_parameters_tolerates_unresolvable_hints():
    def fn(x: int) -> int:
        return x  # pragma: no cover

    fn.__annotations__["x"] = "DoesNotExist"
    assert find_resolved_parameters(fn) == {}


def test_unresolvable_resolver_param_raises_at_registration():
    async def login(mystery: int) -> Login:
        return Login(username="x")  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(login)]) -> str:
        return login.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="cannot be resolved"):
        Tool.from_function(tool)
