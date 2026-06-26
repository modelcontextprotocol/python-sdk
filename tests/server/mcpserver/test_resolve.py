"""Tests for resolver dependency injection (MRTR) on MCPServer tools."""

from typing import Annotated

import pytest
from mcp_types import ElicitRequestParams, ElicitResult, TextContent
from pydantic import BaseModel, Field

from mcp import Client
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import (
    AcceptedElicitation,
    CancelledElicitation,
    Context,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    MCPServer,
    Resolve,
)
from mcp.server.mcpserver.exceptions import InvalidSignature
from mcp.server.mcpserver.resolve import _resolver_key, find_resolved_parameters
from mcp.server.mcpserver.tools.base import Tool


class Login(BaseModel):
    username: str


class Confirm(BaseModel):
    ok: bool


async def _alias_login(ctx: Context) -> Login:
    return Login(username="x")  # pragma: no cover - only the signature is inspected


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
    async def whoami(login: Annotated[ElicitationResult[Login], Resolve(login)]) -> str:
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


def test_elicitation_result_alias_resolves_under_postponed_annotations():
    # Reproduces the case where `from __future__ import annotations` stringifies
    # `Annotated[ElicitationResult[Login], Resolve(_alias_login)]`: the alias must be
    # subscriptable so the resolver is detected (not silently dropped) and the
    # consumer is recognized as wanting the result union.
    def tool(login: str) -> str:
        return login  # pragma: no cover

    tool.__annotations__["login"] = "Annotated[ElicitationResult[Login], Resolve(_alias_login)]"
    resolved = find_resolved_parameters(tool)
    assert "login" in resolved
    assert resolved["login"][1] is True  # wants_union


def test_unresolvable_resolver_param_raises_at_registration():
    async def login(mystery: int) -> Login:
        return Login(username="x")  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(login)]) -> str:
        return login.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="cannot be resolved"):
        Tool.from_function(tool)


def test_resolve_marker_on_return_annotation_is_ignored():
    async def login(ctx: Context) -> Login:
        return Login(username="x")  # pragma: no cover

    async def tool(repo: str) -> Annotated[str, Resolve(login)]:
        return repo  # pragma: no cover

    assert find_resolved_parameters(tool) == {}


def test_callable_object_resolver_error_uses_type_name():
    class BadResolver:
        async def __call__(self, mystery: int) -> Login:
            return Login(username="x")  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(BadResolver())]) -> str:
        return login.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="'BadResolver'"):
        Tool.from_function(tool)


@pytest.mark.anyio
async def test_by_name_resolver_param_uses_aliased_tool_arg():
    mcp = MCPServer(name="Aliased")

    # `schema` collides with a BaseModel attribute, so func_metadata aliases the field;
    # the runtime kwarg key is the alias, which is what a by-name resolver must match.
    async def upper(schema: str) -> Login:
        return Login(username=schema.upper())

    @mcp.tool()
    async def run(schema: str, shouted: Annotated[Login, Resolve(upper)]) -> str:
        return shouted.username

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "run", {"schema": "gpt"}) == "GPT"


@pytest.mark.anyio
async def test_resolver_may_return_non_basemodel_value():
    mcp = MCPServer(name="NonModel")

    async def get_token(ctx: Context) -> str:
        return "secret-token"

    @mcp.tool()
    async def use_token(token: Annotated[str, Resolve(get_token)]) -> str:
        return token

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "use_token", {}) == "secret-token"


@pytest.mark.anyio
async def test_resolver_accepts_optional_context_annotation():
    mcp = MCPServer(name="OptionalContext")

    async def whoami(ctx: Context | None) -> str:
        assert ctx is not None
        return "has-context"

    @mcp.tool()
    async def run(who: Annotated[str, Resolve(whoami)]) -> str:
        return who

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "run", {}) == "has-context"


@pytest.mark.anyio
async def test_bound_method_resolver_runs_once_across_references():
    mcp = MCPServer(name="BoundMethod")
    calls = 0

    class Service:
        async def token(self, ctx: Context) -> str:
            nonlocal calls
            calls += 1
            return "tok"

    service = Service()

    # Each `service.token` access is a fresh bound-method object; keying by the
    # callable (not id) keeps the resolver memoized to a single call.
    async def downstream(token: Annotated[str, Resolve(service.token)]) -> str:
        return token.upper()

    @mcp.tool()
    async def run(
        token: Annotated[str, Resolve(service.token)],
        shouted: Annotated[str, Resolve(downstream)],
    ) -> str:
        return f"{token}:{shouted}"

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "run", {}) == "tok:TOK"
    assert calls == 1


def test_bound_method_cycle_is_detected():
    class Service:
        async def a(self, dep: Login) -> Login:
            return dep  # pragma: no cover

        async def b(self, dep: Login) -> Login:
            return dep  # pragma: no cover

    service = Service()
    service.a.__func__.__annotations__["dep"] = Annotated[Login, Resolve(service.b)]
    service.b.__func__.__annotations__["dep"] = Annotated[Login, Resolve(service.a)]

    async def tool(value: Annotated[Login, Resolve(service.a)]) -> str:
        return value.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="cyclic"):
        Tool.from_function(tool)


@pytest.mark.anyio
async def test_resolver_and_body_see_the_same_validated_default():
    mcp = MCPServer(name="DefaultFactory")
    counter = {"n": 0}

    def next_id() -> int:
        counter["n"] += 1
        return counter["n"]

    # A by-name resolver and the tool body must observe one validation pass, so the
    # `default_factory` runs once and both see the same generated value.
    async def echo_id(request_id: int) -> int:
        return request_id

    @mcp.tool()
    async def run(
        request_id: Annotated[int, Field(default_factory=next_id)],
        resolved_id: Annotated[int, Resolve(echo_id)],
    ) -> str:
        return f"{request_id}:{resolved_id}"

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "run", {}) == "1:1"
    assert counter["n"] == 1


def test_resolver_key_is_stable_for_methods_and_distinct_callables():
    class Service:
        def handler(self) -> None: ...  # pragma: no cover

    a, b = Service(), Service()

    # Pure-python bound methods: stable across accesses, distinct per instance.
    assert _resolver_key(a.handler) == _resolver_key(a.handler)
    assert _resolver_key(a.handler) != _resolver_key(b.handler)

    # Built-in bound methods (no `__func__`): fresh object each access, but the key
    # is stable and keyed to `__self__`.
    items: list[int] = []
    others: list[int] = []
    assert _resolver_key(items.append) == _resolver_key(items.append)
    assert _resolver_key(items.append) != _resolver_key(others.append)
    assert _resolver_key(items.append) != _resolver_key(items.pop)

    # Plain functions key by identity.
    def fn() -> None: ...  # pragma: no cover

    assert _resolver_key(fn) == _resolver_key(fn)
