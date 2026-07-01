"""Tests for resolver dependency injection (MRTR) on MCPServer tools."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal, TypeVar, cast

import anyio
import pytest
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    CallToolResult,
    CreateMessageRequest,
    CreateMessageRequestParams,
    CreateMessageResult,
    CreateMessageResultWithTools,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    InputRequiredResult,
    InputResponses,
    ListRootsResult,
    Root,
    SamplingCapability,
    SamplingMessage,
    SamplingToolsCapability,
    TextContent,
    ToolChoice,
)
from mcp_types import (
    Tool as SamplingTool,
)
from pydantic import BaseModel, Field, FileUrl, ValidationError, create_model
from typing_extensions import TypeAliasType

from mcp import Client, InputRequiredRoundsExceededError
from mcp.client import ClientRequestContext
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import (
    AcceptedElicitation,
    AESGCMRequestStateCodec,
    CancelledElicitation,
    Context,
    DeclinedElicitation,
    Elicit,
    ElicitationResult,
    ListRoots,
    MCPServer,
    RequestStateBoundary,
    RequestStateSecurity,
    Resolve,
    Sample,
)
from mcp.server.mcpserver.exceptions import InvalidSignature
from mcp.server.mcpserver.resolve import (
    _check_elicit_return,
    _decode_state,
    _encode_state,
    _outcome_from_state,
    _render_request,
    _request_digest,
    _resolver_key,
    _state_key,
    _StateEntry,
    _uses_input_required,
    find_resolved_parameters,
    returns_input_required,
)
from mcp.server.mcpserver.tools.base import Tool
from mcp.shared.exceptions import MCPError


def _question_digest(elicit: Elicit[Any]) -> str:
    """The digest `_fulfil` pins: the rendered request the client would be shown."""
    return _request_digest(_render_request(elicit))


class Login(BaseModel):
    username: str


class Confirm(BaseModel):
    ok: bool


class Restock(BaseModel):
    needed: bool


# The `type X = ...` spelling of an InputRequiredResult-bearing return annotation,
# bare and generic (a subscripted alias forwards `__value__` to its origin).
IRRAlias = TypeAliasType("IRRAlias", InputRequiredResult | str)
T_alias = TypeVar("T_alias")
IRRAliasGeneric = TypeAliasType("IRRAliasGeneric", InputRequiredResult | T_alias, type_params=(T_alias,))


class _UnevaluableAlias:
    """Stand-in for `type X = GhostType | str` whose names exist only under
    TYPE_CHECKING: accessing `__value__` evaluates the alias and raises."""

    @property
    def __value__(self) -> Any:
        raise NameError("name 'GhostType' is not defined")


class Handle(BaseModel):
    user_name: str = Field(alias="userName")


class Account(BaseModel):
    user_name: str = Field(validation_alias="vUser", serialization_alias="sUser")


async def _alias_login(ctx: Context) -> Login:
    return Login(username="x")  # pragma: no cover - only the signature is inspected


def _accept(content: dict[str, str | int | float | bool | list[str] | None]):
    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content=content)

    return callback


async def _decline(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    return ElicitResult(action="decline")


async def _never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
    # Declares the form elicitation capability for clients that drive the
    # input_required loop manually; the auto-driver never invokes it.
    raise AssertionError("should not be called")


async def _text(client: Client, tool: str, args: dict[str, object]) -> str:
    result = await client.call_tool(tool, args)
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    return result.content[0].text


def _answer_round(
    result: InputRequiredResult, answer: Callable[[str, ElicitRequestFormParams], ElicitResult]
) -> InputResponses:
    """Fulfil every question in one `InputRequiredResult` round via `answer(key, request_params)`."""
    assert result.input_requests is not None
    responses: InputResponses = {}
    for key, req in result.input_requests.items():
        assert isinstance(req.params, ElicitRequestFormParams)
        responses[key] = answer(key, req.params)
    return responses


# Fixed key shared with servers under test, so tests can unseal minted wire
# state and seal crafted state the server will accept.
_PIN_KEY = b"0123456789abcdef0123456789abcdef"


def _unseal_inner(request_state: str | None) -> str:
    """Unseal a wire `request_state` minted under `_PIN_KEY` into the inner plaintext state."""
    assert request_state is not None
    claims = json.loads(AESGCMRequestStateCodec([_PIN_KEY]).unseal(request_state))
    inner = claims["s"]
    assert isinstance(inner, str)
    return inner


def _outcomes_on_the_wire(request_state: str | None) -> dict[str, Any]:
    """Unseal a wire `request_state` minted under `_PIN_KEY` and return its outcomes."""
    return json.loads(_unseal_inner(request_state))["outcomes"]


def _sealed_state(inner: str, *, tool: str, args: dict[str, Any], audience: str) -> str:
    """Seal a hand-built inner state exactly as the boundary does for a `tools/call` retry.

    The production `RequestStateBoundary._seal` binds method, tool, arguments, and
    audience (the server name), so the test must then call exactly `tool` with
    exactly `args` on the MCPServer named `audience`.
    """
    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
        params={"name": tool, "arguments": args},
    )
    return RequestStateBoundary(RequestStateSecurity(keys=[_PIN_KEY]), default_audience=audience)._seal(ctx, inner)


def _wire_key(fn: Callable[..., Any]) -> str:
    return f"{fn.__module__}:{fn.__qualname__}"


@pytest.mark.anyio
async def test_resolver_returns_value_directly_without_eliciting():
    mcp = MCPServer(name="Direct", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="Accept", request_state_security=RequestStateSecurity.ephemeral())

    async def login(ctx: Context) -> Login | Elicit[Login]:
        return Elicit("GitHub username?", Login)

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(login)]) -> str:
        return login.username

    async with Client(mcp, mode="legacy", elicitation_callback=_accept({"username": "octocat"})) as client:
        assert await _text(client, "whoami", {}) == "octocat"


@pytest.mark.anyio
async def test_consumer_receives_result_union_and_branches():
    mcp = MCPServer(name="Union", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="UnionDecline", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="UnwrappedDecline", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="Nested", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="ExactlyOnce", request_state_security=RequestStateSecurity.ephemeral())
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
    mcp = MCPServer(name="Sync", request_state_security=RequestStateSecurity.ephemeral())

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


def test_multiple_elicit_arms_raise_at_registration():
    # The runtime can honor only one static question schema per resolver, so an
    # ambiguous `-> Elicit[A] | Elicit[B]` must not register (the second arm used
    # to be silently ignored).
    async def ambiguous(ctx: Context) -> Elicit[Login] | Elicit[Confirm]:
        raise NotImplementedError  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(ambiguous)]) -> str:
        return login.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="multiple Elicit/Sample/ListRoots arms"):
        Tool.from_function(tool)


def test_resolve_marker_inside_a_union_raises_at_registration():
    async def login(ctx: Context) -> Login:
        return Login(username="x")  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(login)] | None = None) -> str:
        return login.username if login else ""  # pragma: no cover

    with pytest.raises(InvalidSignature, match="wraps `Resolve"):
        Tool.from_function(tool)


def test_bare_elicitation_result_alias_wants_the_outcome_union():
    # The bare `ElicitationResult` alias (no `[T]` subscription) must still opt into
    # the result union, not be treated as wanting the unwrapped model.
    async def login(ctx: Context) -> Login:
        return Login(username="x")  # pragma: no cover

    async def tool(login: object) -> str:
        return "x"  # pragma: no cover

    bare_alias: Any = ElicitationResult
    tool.__annotations__["login"] = Annotated[bare_alias, Resolve(login)]
    (_, wants_union) = find_resolved_parameters(tool)["login"]
    assert wants_union is True


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
    mcp = MCPServer(name="Aliased", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="NonModel", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="OptionalContext", request_state_security=RequestStateSecurity.ephemeral())

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
    mcp = MCPServer(name="BoundMethod", request_state_security=RequestStateSecurity.ephemeral())
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
    mcp = MCPServer(name="DefaultFactory", request_state_security=RequestStateSecurity.ephemeral())
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


def _delete_folder_server() -> tuple[MCPServer, dict[str, list[str]]]:
    """The `delete_folder` example from docs/migration.md, wired to an in-memory fs."""
    mcp = MCPServer(name="files", request_state_security=RequestStateSecurity.ephemeral())
    fs: dict[str, list[str]] = {}

    async def confirm_delete(path: str) -> Confirm | Elicit[Confirm]:
        file_count = len(fs.get(path, []))
        if file_count == 0:
            return Confirm(ok=True)
        return Elicit(f"{path} has {file_count} file(s). Delete anyway?", Confirm)

    @mcp.tool()
    async def delete_folder(
        path: str,
        confirm: Annotated[ElicitationResult[Confirm], Resolve(confirm_delete)],
    ) -> str:
        match confirm:
            case AcceptedElicitation(data=Confirm(ok=True)):
                fs.pop(path, None)
                return f"deleted {path}"
            case AcceptedElicitation():
                return "kept the folder"
            case DeclinedElicitation():
                return "declined: folder not deleted"
            case CancelledElicitation():  # pragma: no branch
                return "cancelled: folder not deleted"

    return mcp, fs


@pytest.mark.anyio
async def test_delete_empty_folder_does_not_elicit():
    mcp, fs = _delete_folder_server()
    fs["/empty"] = []

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit for an empty folder")

    async with Client(mcp, mode="legacy", elicitation_callback=never) as client:
        assert await _text(client, "delete_folder", {"path": "/empty"}) == "deleted /empty"
    assert "/empty" not in fs


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "content", "expected"),
    [
        ("accept", {"ok": True}, "deleted /docs"),
        ("accept", {"ok": False}, "kept the folder"),
        ("decline", None, "declined: folder not deleted"),
        ("cancel", None, "cancelled: folder not deleted"),
    ],
)
async def test_delete_non_empty_folder_handles_every_outcome(
    action: Literal["accept", "decline", "cancel"],
    content: dict[str, str | int | float | bool | list[str] | None] | None,
    expected: str,
):
    mcp, fs = _delete_folder_server()
    fs["/docs"] = ["a.txt", "b.txt"]

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert "/docs has 2 file(s)" in params.message
        return ElicitResult(action=action, content=content)

    async with Client(mcp, mode="legacy", elicitation_callback=callback) as client:
        assert await _text(client, "delete_folder", {"path": "/docs"}) == expected
    assert ("/docs" in fs) is (expected != "deleted /docs")


@pytest.mark.anyio
async def test_input_required_first_round_returns_the_question():
    mcp, fs = _delete_folder_server()
    fs["/docs"] = ["a.txt", "b.txt"]

    async with Client(mcp, elicitation_callback=_never) as client:  # mode="auto" negotiates 2026-07-28
        assert client.session.protocol_version == "2026-07-28"
        result = await client.session.call_tool("delete_folder", {"path": "/docs"}, allow_input_required=True)
        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        (request,) = result.input_requests.values()
        assert request.method == "elicitation/create"
        assert "/docs has 2 file(s)" in request.params.message
        assert result.request_state is not None
    assert "/docs" in fs  # nothing deleted before the answer arrives


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "content", "expected"),
    [
        ("accept", {"ok": True}, "deleted /docs"),
        ("accept", {"ok": False}, "kept the folder"),
        ("decline", None, "declined: folder not deleted"),
        ("cancel", None, "cancelled: folder not deleted"),
    ],
)
async def test_input_required_loop_handles_every_outcome(
    action: Literal["accept", "decline", "cancel"],
    content: dict[str, str | int | float | bool | list[str] | None] | None,
    expected: str,
):
    # End-to-end at 2026-07-28: the client's auto-driver answers the embedded
    # elicitation through the ordinary `elicitation_callback` and retries.
    mcp, fs = _delete_folder_server()
    fs["/docs"] = ["a.txt", "b.txt"]

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        assert "/docs has 2 file(s)" in params.message
        return ElicitResult(action=action, content=content)

    async with Client(mcp, elicitation_callback=callback) as client:  # mode="auto" negotiates 2026-07-28
        result = await client.call_tool("delete_folder", {"path": "/docs"})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == expected
    assert ("/docs" in fs) is (expected != "deleted /docs")


@pytest.mark.anyio
async def test_input_required_empty_folder_completes_without_eliciting():
    mcp, fs = _delete_folder_server()
    fs["/empty"] = []

    async def never(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit for an empty folder")

    async with Client(mcp, elicitation_callback=never) as client:
        result = await client.call_tool("delete_folder", {"path": "/empty"})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "deleted /empty"
    assert "/empty" not in fs


@pytest.mark.anyio
async def test_input_required_asks_each_question_once_while_bodies_rerun():
    mcp = MCPServer(name="ExactlyOnceMRTR", request_state_security=RequestStateSecurity.ephemeral())
    counts = {"login": 0, "confirm": 0}

    async def login(ctx: Context) -> Login | Elicit[Login]:
        counts["login"] += 1
        return Elicit("Username?", Login)

    async def confirm(login: Annotated[Login, Resolve(login)]) -> Elicit[Confirm]:
        counts["confirm"] += 1
        return Elicit(f"As {login.username}?", Confirm)

    @mcp.tool()
    async def act(
        login: Annotated[Login, Resolve(login)],
        confirm: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        return f"{login.username}:{confirm.ok}"

    asked: list[str] = []

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params.message)
        if "Username" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        result = await client.call_tool("act", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"

    # `confirm` can only form its question from `login`'s answer, so the auto-driver
    # sees the questions in two successive rounds and answers each exactly once.
    assert asked == ["Username?", "As octocat?"]
    # The once-per-call guarantee is about the question, not the body: a recorded
    # answer is consulted only after the body asks again, so `login` runs on every
    # round the call passes through (asks in round 1, consumes its answer in round 2,
    # re-asks-and-restores in round 3) while the user is prompted exactly once.
    # `confirm` only forms its question once `login` is known: it asks in round 2
    # and consumes in round 3.
    assert counts == {"login": 3, "confirm": 2}


@pytest.mark.anyio
async def test_input_required_batches_independent_elicits_in_one_round():
    mcp = MCPServer(name="BatchedMRTR", request_state_security=RequestStateSecurity.ephemeral())

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    async def ask_confirm(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Confirm?", Confirm)

    @mcp.tool()
    async def both(
        name: Annotated[Login, Resolve(ask_name)],
        confirm: Annotated[Confirm, Resolve(ask_confirm)],
    ) -> str:
        return f"{name.username}:{confirm.ok}"

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        if "Name" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=_never) as client:
        # Both independent resolvers are asked together in the first round.
        first = await client.session.call_tool("both", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert len(first.input_requests) == 2

        # Answering both and echoing `request_state` completes in a single retry.
        final = await client.session.call_tool(
            "both",
            {},
            input_responses=_answer_round(first, answer),
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat:True"


@pytest.mark.anyio
async def test_auto_driver_answers_independent_questions_in_a_single_round():
    # The pure `count_round` resolver is never persisted in `request_state`, so it
    # re-runs on every round: its run count is the number of rounds the call took.
    mcp = MCPServer(name="AutoBatch", request_state_security=RequestStateSecurity.ephemeral())
    rounds = 0

    async def count_round(ctx: Context) -> int:
        nonlocal rounds
        rounds += 1
        return rounds

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    async def ask_confirm(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Confirm?", Confirm)

    @mcp.tool()
    async def both(
        round_no: Annotated[int, Resolve(count_round)],
        name: Annotated[Login, Resolve(ask_name)],
        confirm: Annotated[Confirm, Resolve(ask_confirm)],
    ) -> str:
        return f"{name.username}:{confirm.ok}"

    asked: list[str] = []

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        asked.append(params.message)
        if "Name" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        result = await client.call_tool("both", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"

    # The driver dispatches batched questions concurrently, so order is unspecified.
    assert sorted(asked) == ["Confirm?", "Name?"]  # both questions, each exactly once
    assert rounds == 2  # one question round, then the completing round


def test_uses_input_required_version_gate():
    assert _uses_input_required("2026-07-28") is True
    assert _uses_input_required("2025-11-25") is False
    assert _uses_input_required(None) is False


@pytest.mark.parametrize(
    "request_state",
    [
        None,
        "",
        "not json",
        '{"v": 99, "outcomes": {}}',  # wrong version
        '{"v": 1}',  # missing outcomes
        '{"v": 1, "outcomes": []}',  # outcomes not a dict
        "[1, 2, 3]",  # not an object
    ],
)
def test_decode_state_tolerates_malformed_request_state(request_state: str | None):
    state = _decode_state(request_state)
    assert state.outcomes == {} and state.asked == {}


def test_state_round_trips_accept_decline_cancel():
    entries = {
        "a": _StateEntry(action="accept", data={"username": "octocat"}),
        "b": _StateEntry(action="decline"),
        "c": _StateEntry(action="cancel"),
        "d": _StateEntry(action="accept", data="raw-token"),  # non-dict wire value
    }
    state = _decode_state(_encode_state(entries, {"e": "asked-digest"}))
    decoded = state.outcomes
    assert decoded == entries  # encode-restore is the identity on the stored entries
    assert state.asked == {"e": "asked-digest"}

    ask = Elicit("q", Login)
    accepted = _outcome_from_state(decoded["a"], ask)
    assert isinstance(accepted, AcceptedElicitation) and accepted.data == Login(username="octocat")
    # Decline/cancel entries carry no data; the schema is not consulted for them.
    assert isinstance(_outcome_from_state(decoded["b"], ask), DeclinedElicitation)
    assert isinstance(_outcome_from_state(decoded["c"], ask), CancelledElicitation)
    # An accepted restore always validates against the question's live schema -
    # data that doesn't fit is rejected, never passed through raw.
    with pytest.raises(ValidationError):
        _outcome_from_state(decoded["d"], ask)


def test_check_elicit_return_allows_one_arm_and_rejects_two():
    _check_elicit_return(Elicit[Login], "r")  # bare Elicit[T]
    _check_elicit_return(Login | Elicit[Login], "r")  # union arm
    _check_elicit_return(Login, "r")  # no Elicit arm
    _check_elicit_return(None, "r")  # unannotated
    # A resolver asks one question: two distinct Elicit arms mean it should be split.
    with pytest.raises(InvalidSignature, match="'r' return annotation has multiple Elicit/Sample/ListRoots arms"):
        _check_elicit_return(Elicit[Login] | Elicit[Confirm], "r")


@pytest.mark.anyio
async def test_non_elicitation_response_raises():
    mcp = MCPServer(name="WrongResponse", request_state_security=RequestStateSecurity.ephemeral())

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    @mcp.tool()
    async def tool(name: Annotated[Login, Resolve(ask)]) -> str:
        return name.username  # pragma: no cover

    async with Client(mcp, elicitation_callback=_never) as client:
        r1 = await client.session.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(r1, InputRequiredResult)
        assert r1.input_requests is not None
        (key,) = r1.input_requests
        # Answer with a sampling result instead of an elicitation result.
        r2 = await client.session.call_tool(
            "tool",
            {},
            input_responses={
                key: CreateMessageResult(role="assistant", content=TextContent(type="text", text="x"), model="m")
            },
            request_state=r1.request_state,
            allow_input_required=True,
        )
        assert isinstance(r2, CallToolResult)
        assert r2.is_error
        assert isinstance(r2.content[0], TextContent)
        assert "non-elicitation response" in r2.content[0].text


@pytest.mark.anyio
async def test_direct_call_tool_with_non_eliciting_resolver():
    # `MCPServer.call_tool()` called directly builds a Context with no request, so
    # `ctx.protocol_version` is None. A tool whose resolvers never elicit must still
    # work there (regression: it used to raise "Context is not available").
    mcp = MCPServer(name="Direct", request_state_security=RequestStateSecurity.ephemeral())

    async def whoami(ctx: Context) -> Login:
        return Login(username="direct")

    @mcp.tool()
    async def tool(login: Annotated[Login, Resolve(whoami)]) -> str:
        return login.username

    result = await mcp.call_tool("tool", {}, Context(mcp_server=mcp))
    assert isinstance(result, CallToolResult)
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "direct"


@pytest.mark.anyio
async def test_two_instances_of_one_method_do_not_collide():
    mcp = MCPServer(name="Instances", request_state_security=RequestStateSecurity.ephemeral())

    class Service:
        def __init__(self, name: str) -> None:
            self.name = name

        async def who(self, ctx: Context) -> Login:
            return Login(username=self.name)

    alice, bob = Service("alice"), Service("bob")

    @mcp.tool()
    async def both(
        a: Annotated[Login, Resolve(alice.who)],
        b: Annotated[Login, Resolve(bob.who)],
    ) -> str:
        return f"{a.username},{b.username}"

    result = await mcp.call_tool("both", {}, Context(mcp_server=mcp))
    assert isinstance(result, CallToolResult)
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "alice,bob"


@pytest.mark.anyio
async def test_non_serializable_sibling_resolver_does_not_break_rounds():
    mcp = MCPServer(name="NonSerializable", request_state_security=RequestStateSecurity.ephemeral())

    async def clock(ctx: Context) -> datetime:
        return datetime(2026, 1, 1)

    async def ask(ctx: Context) -> Elicit[Confirm]:
        return Elicit("ok?", Confirm)

    @mcp.tool()
    async def act(
        when: Annotated[datetime, Resolve(clock)],
        confirm: Annotated[Confirm, Resolve(ask)],
    ) -> str:
        return f"{when.year}:{confirm.ok}"

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        result = await client.call_tool("act", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "2026:True"


@pytest.mark.anyio
async def test_bare_elicit_dependency_restored_as_model():
    # A `-> Elicit[Login]` (bare, no union) resolver feeds a dependent resolver. After
    # the round-trip the dependency must come back as a Login model, not a raw dict.
    mcp = MCPServer(name="BareElicitDep", request_state_security=RequestStateSecurity.ephemeral())

    async def login(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    async def confirm(login: Annotated[Login, Resolve(login)]) -> Elicit[Confirm]:
        return Elicit(f"as {login.username}?", Confirm)

    @mcp.tool()
    async def act(
        login: Annotated[Login, Resolve(login)],
        confirm: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        return f"{login.username}:{confirm.ok}"

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        if "user" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        assert "as octocat?" in params.message  # proves login was a real model
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        result = await client.call_tool("act", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_accept_with_no_content_is_an_error_not_a_cancel(mode: Literal["legacy", "auto"]):
    # Both transports must agree: mode="legacy" elicits synchronously mid-call,
    # mode="auto" rides the 2026-07-28 input_required loop.
    mcp = MCPServer(name="AcceptNoContent", request_state_security=RequestStateSecurity.ephemeral())

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def tool(login: Annotated[Login, Resolve(ask)]) -> str:
        return login.username  # pragma: no cover

    async def empty_accept(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="accept", content=None)

    async with Client(mcp, mode=mode, elicitation_callback=empty_accept) as client:
        result = await client.call_tool("tool", {})
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        assert "no content" in result.content[0].text


@pytest.mark.anyio
async def test_eliciting_tool_without_client_capability_is_a_protocol_error():
    # The server must not send an `input_requests` entry the client has not declared
    # capability for: with no `elicitation` declared (no callback), the call fails as
    # a -32021 protocol error, not a CallToolResult execution failure.
    mcp = MCPServer(name="NoElicitationCapability", request_state_security=RequestStateSecurity.ephemeral())

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def tool(login: Annotated[Login, Resolve(ask)]) -> str:
        return login.username  # pragma: no cover

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.call_tool("tool", {}, allow_input_required=True)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data is not None
    assert "elicitation" in exc_info.value.error.data["requiredCapabilities"]


@pytest.mark.anyio
async def test_independent_nested_deps_batch_into_one_round():
    mcp = MCPServer(name="NestedBatch", request_state_security=RequestStateSecurity.ephemeral())

    async def ask_a(ctx: Context) -> Elicit[Login]:
        return Elicit("A name?", Login)

    async def ask_b(ctx: Context) -> Elicit[Confirm]:
        return Elicit("B confirm?", Confirm)

    # `combine` depends on two independent eliciting resolvers; both must be asked
    # in the same round, not serialized across two InputRequiredResult rounds.
    async def combine(
        a: Annotated[Login, Resolve(ask_a)],
        b: Annotated[Confirm, Resolve(ask_b)],
    ) -> Login:
        return Login(username=f"{a.username}:{b.ok}")

    @mcp.tool()
    async def tool(combined: Annotated[Login, Resolve(combine)]) -> str:
        return combined.username

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        if "name" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert len(first.input_requests) == 2  # batched, not serialized

        final = await client.session.call_tool(
            "tool",
            {},
            input_responses=_answer_round(first, answer),
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat:True"


@pytest.mark.anyio
async def test_deep_chain_keeps_early_answers_across_rounds():
    # A 4-round dependency chain where an early answer (A) must survive in
    # request_state while later resolvers are asked. It must be asked exactly once.
    mcp = MCPServer(name="DeepChain", request_state_security=RequestStateSecurity.ephemeral())

    async def ra(ctx: Context) -> Elicit[Login]:
        return Elicit("A name?", Login)

    async def rb(a: Annotated[Login, Resolve(ra)]) -> Elicit[Confirm]:
        return Elicit("B?", Confirm)

    async def rc(b: Annotated[Confirm, Resolve(rb)]) -> Elicit[Confirm]:
        return Elicit("C?", Confirm)

    async def rd(c: Annotated[Confirm, Resolve(rc)]) -> Elicit[Confirm]:
        return Elicit("D?", Confirm)

    # Depends on `ra` directly AND on `rd` (which transitively needs ra->rb->rc).
    @mcp.tool()
    async def tool(
        a: Annotated[Login, Resolve(ra)],
        d: Annotated[Confirm, Resolve(rd)],
    ) -> str:
        return f"{a.username}:{d.ok}"

    a_asks = 0

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        nonlocal a_asks
        if "name" in params.message:
            a_asks += 1
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        result = await client.call_tool("tool", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"
    assert a_asks == 1  # ra's answer survived in request_state; never re-asked


@pytest.mark.anyio
async def test_factory_closures_get_distinct_wire_keys():
    # Two resolvers from one factory share module:qualname; they must still get
    # distinct questions and their own values (regression: they collided on the wire).
    mcp = MCPServer(name="FactoryClosures", request_state_security=RequestStateSecurity.ephemeral())

    def make(label: str):
        async def resolver(ctx: Context) -> Elicit[Login]:
            return Elicit(f"{label}?", Login)

        return resolver

    ask_a, ask_b = make("A"), make("B")

    @mcp.tool()
    async def tool(
        a: Annotated[Login, Resolve(ask_a)],
        b: Annotated[Login, Resolve(ask_b)],
    ) -> str:
        return f"{a.username},{b.username}"

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        return ElicitResult(action="accept", content={"username": params.message[0]})

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert len(first.input_requests) == 2  # distinct keys, not collapsed to one

        final = await client.session.call_tool(
            "tool",
            {},
            input_responses=_answer_round(first, answer),
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "A,B"


@pytest.mark.anyio
async def test_eliciting_resolver_without_elicit_arm_restores_a_typed_model():
    # A resolver annotated `-> object` that actually returns `Elicit(...)` declares
    # no `Elicit[T]` return arm. Its answer, restored from request_state in a 3+
    # round flow, must still come back as a Login model (not a raw dict): restore
    # validates against the live `Elicit.schema` the body produced, not the lying
    # annotation, so a dependent resolver/tool can use its attributes.
    mcp = MCPServer(name="LyingAnnotation", request_state_security=RequestStateSecurity.ephemeral())

    # Annotated without an `Elicit[T]` return arm; the body asks anyway.
    async def login(ctx: Context) -> object:
        return Elicit("user?", Login)

    async def confirm(login: Annotated[Login, Resolve(login)]) -> Elicit[Confirm]:
        return Elicit(f"as {login.username}?", Confirm)

    @mcp.tool()
    async def act(
        login: Annotated[Login, Resolve(login)],
        confirm: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        return f"{login.username}:{confirm.ok}"

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        if "user" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        assert "as octocat?" in params.message  # login restored as a real model
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        result = await client.call_tool("act", {})
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"


def test_wire_key_is_worker_stable_for_methods_and_callable_objects():
    class Service:
        async def token(self, ctx: Context) -> Login:
            return Login(username="x")  # pragma: no cover

    class CallableResolver:
        async def __call__(self, ctx: Context) -> Login:
            return Login(username="x")  # pragma: no cover

    a, b = Service(), Service()
    # No id(...) in the key: two instances of one method get the same base (they are
    # disambiguated at registration, not here), and the key carries no memory address.
    assert _state_key(a.token) == _state_key(b.token)
    assert "#" not in _state_key(a.token)
    assert _state_key(a.token).endswith("Service.token")
    # Callable objects key by their type's qualname (they have no `__qualname__`).
    assert _state_key(CallableResolver()).endswith("CallableResolver")


@pytest.mark.anyio
async def test_declined_outcome_persists_in_request_state_and_is_not_reasked():
    # A decline is recorded in `request_state` just like an accept: RB elicits only
    # after seeing RA's decline, so RA's outcome must survive into the round that
    # answers RB without RA being asked again.
    mcp = MCPServer(name="DeclinePersists", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ra(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    async def rb(a: Annotated[ElicitationResult[Login], Resolve(ra)]) -> Elicit[Confirm]:
        assert isinstance(a, DeclinedElicitation)
        return Elicit("proceed anonymously?", Confirm)

    @mcp.tool()
    async def act(
        a: Annotated[ElicitationResult[Login], Resolve(ra)],
        c: Annotated[Confirm, Resolve(rb)],
    ) -> str:
        assert isinstance(a, DeclinedElicitation)
        return f"anonymous:{c.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        (ra_key,) = first.input_requests

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={ra_key: ElicitResult(action="decline")},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        (rb_key,) = second.input_requests  # only RB's question; RA is not re-asked
        assert rb_key != ra_key
        assert _outcomes_on_the_wire(second.request_state)[ra_key]["action"] == "decline"

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={rb_key: ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "anonymous:True"


@pytest.mark.anyio
async def test_unknown_response_keys_and_ghost_state_entries_are_ignored():
    # `input_responses` keys the server never asked for and `request_state` outcome
    # entries matching no resolver are tolerated and not echoed into later rounds.
    mcp = MCPServer(name="GhostKeys", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ra(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    async def rb(a: Annotated[Login, Resolve(ra)]) -> Elicit[Confirm]:
        return Elicit(f"as {a.username}?", Confirm)

    @mcp.tool()
    async def act(
        a: Annotated[Login, Resolve(ra)],
        c: Annotated[Confirm, Resolve(rb)],
    ) -> str:
        return f"{a.username}:{c.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert first.request_state is not None
        (ra_key,) = first.input_requests

        spliced = json.loads(_unseal_inner(first.request_state))
        # A well-formed v2 entry under an unknown key: dropped as unknown, not as malformed.
        spliced["outcomes"]["ghost"] = {
            "action": "accept",
            "data": {"username": "spooky"},
            "q": _question_digest(Elicit("user?", Login)),
        }
        second = await client.session.call_tool(
            "act",
            {},
            input_responses={
                ra_key: ElicitResult(action="accept", content={"username": "octocat"}),
                "ghost": ElicitResult(action="accept", content={"username": "spooky"}),
            },
            request_state=_sealed_state(json.dumps(spliced), tool="act", args={}, audience="GhostKeys"),
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        (rb_key,) = second.input_requests
        outcomes = _outcomes_on_the_wire(second.request_state)
        assert ra_key in outcomes
        assert "ghost" not in outcomes  # the spliced entry is dropped, not carried onward

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={rb_key: ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat:True"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "forged_data",
    [
        pytest.param("not-a-dict", id="non-dict-data"),
        pytest.param({"hacked": True}, id="dict-failing-schema"),
    ],
)
async def test_forged_state_entry_failing_the_schema_is_reasked_not_an_error(forged_data: str | dict[str, bool]):
    # Authenticated state is not schema-trusted: a failing accept entry reads as no progress and is re-asked.
    mcp = MCPServer(name="ForgedState", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(ask)]) -> str:
        return login.username

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("whoami", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert first.request_state is not None
        (key,) = first.input_requests

        forged = json.loads(_unseal_inner(first.request_state))
        # The digest matches the live question, so the entry stands or falls on schema alone.
        forged["outcomes"][key] = {
            "action": "accept",
            "data": forged_data,
            "q": _question_digest(Elicit("user?", Login)),
        }
        second = await client.session.call_tool(
            "whoami",
            {},
            request_state=_sealed_state(json.dumps(forged), tool="whoami", args={}, audience="ForgedState"),
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)  # re-asked, not an error
        assert second.input_requests is not None
        assert set(second.input_requests) == {key}
        assert _outcomes_on_the_wire(second.request_state) == {}  # the forged entry is dropped

        final = await client.session.call_tool(
            "whoami",
            {},
            input_responses={key: ElicitResult(action="accept", content={"username": "octocat"})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat"


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_schema_mismatched_fresh_answer_fails_the_call_without_pydantic_leakage(mode: Literal["legacy", "auto"]):
    # An accepted answer whose content fails the requested schema fails the call
    # with the framework's own message on both transports; pydantic's error text
    # (which carries an "errors.pydantic.dev" link) must not leak to the client.
    mcp = MCPServer(name="MismatchedAnswer", request_state_security=RequestStateSecurity.ephemeral())

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(ask)]) -> str:
        raise NotImplementedError  # pragma: no cover - the mismatched answer never reaches the body

    async with Client(mcp, mode=mode, elicitation_callback=_accept({"nope": "x"})) as client:
        result = await client.call_tool("whoami", {})
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        text = result.content[0].text
        assert "does not match the requested schema" in text
        assert "errors.pydantic.dev" not in text
        if mode == "auto":
            assert "Resolver" in text  # the input_required transport names the offending resolver key
        else:
            assert "Received an accepted elicitation" in text  # the legacy path has no wire key to name


@pytest.mark.anyio
async def test_auto_driver_gives_up_when_the_chain_outlasts_its_round_budget():
    # A dependency chain of 11 eliciting resolvers needs 11 retry rounds, one more
    # than the default `input_required_max_rounds`, so `client.call_tool` must raise
    # rather than loop on. The pure `count_leg` resolver is never persisted, so it
    # re-runs on every server leg: its final value is the exact number of legs.
    mcp = MCPServer(name="TooDeep", request_state_security=RequestStateSecurity.ephemeral())
    legs = 0

    async def count_leg(ctx: Context) -> int:
        nonlocal legs
        legs += 1
        return legs

    async def root(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Q1?", Confirm)

    def extend(dep: Callable[..., Any], n: int) -> Callable[..., Any]:
        async def link(prev: Annotated[Confirm, Resolve(dep)]) -> Elicit[Confirm]:
            return Elicit(f"Q{n}?", Confirm)

        return link

    chain: Callable[..., Any] = root
    for n in range(2, 12):  # 11 eliciting resolvers in total
        chain = extend(chain, n)

    @mcp.tool()
    async def long_haul(
        leg: Annotated[int, Resolve(count_leg)],
        last: Annotated[Confirm, Resolve(chain)],
    ) -> str:
        raise NotImplementedError  # pragma: no cover - the driver gives up first

    answered = 0

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        nonlocal answered
        answered += 1
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=callback) as client:
        with anyio.fail_after(5):  # the loop must end by raising, not spin on retries
            with pytest.raises(InputRequiredRoundsExceededError) as exc_info:
                await client.call_tool("long_haul", {})
        assert exc_info.value.max_rounds == client.input_required_max_rounds
        assert answered == client.input_required_max_rounds  # one question answered per retry round
        assert legs == client.input_required_max_rounds + 1  # the initial call plus one leg per retry


@pytest.mark.anyio
async def test_aliased_elicitation_model_round_trips_through_request_state():
    # The stored entry is the client's raw wire content, so it restores through
    # the same validation the answer originally passed - aliases and all. A
    # re-derived (field-name) shape would fail validation on the round after
    # next, drop the stored answer, and re-ask the user forever.
    mcp = MCPServer(name="AliasState", request_state_security=RequestStateSecurity.ephemeral())

    async def who(ctx: Context) -> Elicit[Handle]:
        return Elicit("handle?", Handle)

    async def confirm(h: Annotated[Handle, Resolve(who)]) -> Elicit[Confirm]:
        return Elicit(f"go as {h.user_name}?", Confirm)

    @mcp.tool()
    async def act(
        h: Annotated[Handle, Resolve(who)],
        c: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        return f"{h.user_name}:{c.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        (who_key,) = first.input_requests

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={who_key: ElicitResult(action="accept", content={"userName": "octocat"})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        (confirm_key,) = second.input_requests  # only the dependent question; the stored answer holds
        assert confirm_key != who_key

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={confirm_key: ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat:True"


@pytest.mark.anyio
async def test_divergent_validation_and_serialization_aliases_round_trip():
    # `request_state` must carry the client's answer exactly as it was sent: the
    # rendered question is validation-aliased, so re-deriving the stored shape from
    # the validated model (which serializes under the *serialization* alias) would
    # produce data the schema's own validation rejects, dropping the stored answer
    # on the round after next and re-asking the user.
    mcp = MCPServer(name="DivergentAliases", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def who(ctx: Context) -> Elicit[Account]:
        return Elicit("account?", Account)

    async def confirm(a: Annotated[Account, Resolve(who)]) -> Elicit[Confirm]:
        return Elicit(f"go as {a.user_name}?", Confirm)

    @mcp.tool()
    async def act(
        a: Annotated[Account, Resolve(who)],
        c: Annotated[Confirm, Resolve(confirm)],
    ) -> str:
        return f"{a.user_name}:{c.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        (who_key,) = first.input_requests
        question = first.input_requests[who_key].params
        assert isinstance(question, ElicitRequestFormParams)
        assert "vUser" in question.requested_schema["properties"]  # the client answers validation-aliased

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={who_key: ElicitResult(action="accept", content={"vUser": "octocat"})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        (go_key,) = second.input_requests  # only the dependent question; the stored answer holds
        assert go_key != who_key
        # The stored entry is the client's wire content, not a re-serialization of it.
        assert _outcomes_on_the_wire(second.request_state)[who_key]["data"] == {"vUser": "octocat"}

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={go_key: ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat:True"


@pytest.mark.anyio
async def test_state_entry_never_replaces_a_resolver_computed_value():
    # `request_state` is client-echoed: an accept entry under a resolver's wire key
    # must only satisfy a question the resolver is actually asking, never stand in
    # for the body's own computation on a branch that does not ask.
    mcp = MCPServer(name="StateVsBody", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))
    calls = {"decide": 0}

    async def decide(ctx: Context) -> Restock | Elicit[Restock]:
        calls["decide"] += 1
        return Restock(needed=False)  # this branch computes server-side; no question

    @mcp.tool()
    async def plan_restock(restock: Annotated[Restock, Resolve(decide)]) -> str:
        return str(restock.needed)

    # A decodable v2 entry; the resolver never asks, so it must go unconsulted, not dropped as malformed.
    entry = {"action": "accept", "data": {"needed": True}, "q": _question_digest(Elicit("Restock?", Restock))}
    crafted = json.dumps({"v": 3, "outcomes": {_wire_key(decide): entry}})

    async with Client(mcp, elicitation_callback=_never) as client:
        result = await client.session.call_tool(
            "plan_restock",
            {},
            request_state=_sealed_state(crafted, tool="plan_restock", args={}, audience="StateVsBody"),
            allow_input_required=True,
        )
        assert isinstance(result, CallToolResult)
        assert isinstance(result.content[0], TextContent)
        # The body ran and its computation won; the crafted entry was never consulted.
        assert result.content[0].text == "False"
        assert calls["decide"] == 1


@pytest.mark.anyio
async def test_state_decline_entry_for_a_pure_resolver_is_ignored():
    # A decline/cancel entry can only answer a question; a resolver with no Elicit
    # arm never asks one, so such an entry cannot suppress its computed value.
    mcp = MCPServer(name="PureVsDecline", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def lookup(ctx: Context) -> Login:
        return Login(username="server-side")

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(lookup)]) -> str:
        return login.username

    # A decodable v2 entry: `lookup` never asks, so no digest can make the decline apply.
    entry = {"action": "decline", "q": _question_digest(Elicit("user?", Login))}
    crafted = json.dumps({"v": 3, "outcomes": {_wire_key(lookup): entry}})

    async with Client(mcp, elicitation_callback=_never) as client:
        result = await client.session.call_tool(
            "whoami",
            {},
            request_state=_sealed_state(crafted, tool="whoami", args={}, audience="PureVsDecline"),
            allow_input_required=True,
        )
        assert isinstance(result, CallToolResult)
        assert not result.is_error
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "server-side"


@pytest.mark.anyio
async def test_dynamic_schema_resolver_restores_across_rounds():
    # `-> Elicit[BaseModel]` is the natural annotation for `create_model(...)`
    # schemas; the restored answer must validate against the live question's
    # schema, so the dynamic shape works across a multi-question chain.
    mcp = MCPServer(name="DynamicSchema", request_state_security=RequestStateSecurity.ephemeral())
    dyn = create_model("Dyn", token=(str, ...))

    async def first(ctx: Context) -> Elicit[BaseModel]:
        return Elicit("Q1?", dyn)

    async def second(f: Annotated[BaseModel, Resolve(first)], ctx: Context) -> Elicit[Confirm]:
        return Elicit("Q2?", Confirm)

    @mcp.tool()
    async def chain(c: Annotated[Confirm, Resolve(second)]) -> str:
        return str(c.ok)

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        if "Q1" in params.message:
            return ElicitResult(action="accept", content={"token": "t"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp, elicitation_callback=_never) as client:
        one = await client.session.call_tool("chain", {}, allow_input_required=True)
        assert isinstance(one, InputRequiredResult)
        two = await client.session.call_tool(
            "chain",
            {},
            input_responses=_answer_round(one, answer),
            request_state=one.request_state,
            allow_input_required=True,
        )
        assert isinstance(two, InputRequiredResult)  # Q1 consumed, Q2 asked
        final = await client.session.call_tool(
            "chain",
            {},
            input_responses=_answer_round(two, answer),
            request_state=two.request_state,
            allow_input_required=True,
        )
        # Round 3 restores Q1's answer against the live dynamic schema and completes.
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "True"


@pytest.mark.parametrize(
    "annotation",
    [
        InputRequiredResult,
        InputRequiredResult | str,
        Annotated[InputRequiredResult | str, "meta"],
        str | Annotated[InputRequiredResult, "meta"],  # Annotated as a union member
        IRRAlias,  # `type X = ...` alias
        IRRAliasGeneric[str],  # subscripted generic alias
    ],
)
def test_tool_combining_resolvers_with_input_required_return_is_rejected(annotation: Any):
    # A call has one input_responses/request_state channel: resolver elicitation
    # and a hand-rolled InputRequiredResult body cannot share it.
    mcp = MCPServer(name="ChannelOwnership", request_state_security=RequestStateSecurity.ephemeral())

    async def lookup(ctx: Context) -> Login:
        return Login(username="x")  # pragma: no cover - registration is rejected

    async def combo(login: Annotated[Login, Resolve(lookup)]):
        raise NotImplementedError  # pragma: no cover

    combo.__annotations__["return"] = annotation
    with pytest.raises(InvalidSignature, match="combines Resolve\\(\\.\\.\\.\\) parameters"):
        mcp.tool()(combo)

    # Without resolver parameters the hand-rolled form remains available.
    @mcp.tool()
    async def manual() -> InputRequiredResult:
        raise NotImplementedError  # pragma: no cover - only registration is exercised

    assert returns_input_required(manual)


def test_unevaluable_alias_and_parameterized_generics_declare_no_arm():
    # A `type X = ...` alias is evaluated lazily, so one naming TYPE_CHECKING-only
    # imports raises NameError on `__value__` access: it declares no arm the check
    # can see and must not break registration (the in-call guard still covers a
    # body that returns an InputRequiredResult anyway). A parameterized generic
    # return is never the InputRequiredResult class either.
    mcp = MCPServer(name="RegistrationTolerance", request_state_security=RequestStateSecurity.ephemeral())

    async def lookup(ctx: Context) -> Login:
        return Login(username="x")  # pragma: no cover - only registration is exercised

    async def lazy(login: Annotated[Login, Resolve(lookup)]):
        raise NotImplementedError  # pragma: no cover

    lazy.__annotations__["return"] = _UnevaluableAlias()
    assert not returns_input_required(lazy)

    @mcp.tool()
    async def listy(login: Annotated[Login, Resolve(lookup)]) -> list[str]:
        raise NotImplementedError  # pragma: no cover

    assert not returns_input_required(listy)


@pytest.mark.anyio
async def test_tool_returning_input_required_dynamically_with_resolvers_is_an_error():
    # The annotated form of this combination is rejected at registration; a body
    # that returns an InputRequiredResult without declaring it fails loudly at the
    # same boundary instead of silently fighting the resolvers for the channel.
    mcp = MCPServer(name="DynamicChannelClash", request_state_security=RequestStateSecurity.ephemeral())

    async def lookup(ctx: Context) -> Login:
        return Login(username="x")

    @mcp.tool()
    async def sneaky(login: Annotated[Login, Resolve(lookup)]):
        return InputRequiredResult(input_requests={}, request_state="opaque")

    async with Client(mcp) as client:
        result = await client.call_tool("sneaky", {})
        assert result.is_error
        assert isinstance(result.content[0], TextContent)
        assert "the multi-round flow is driven either by resolvers or by the tool body" in result.content[0].text


def test_question_digest_pins_the_rendered_question():
    # Computed over the rendered wire question: identical Elicits agree, any change diverges.
    digest = _question_digest(Elicit("Name?", Login))
    assert digest == _question_digest(Elicit("Name?", Login))
    assert digest != _question_digest(Elicit("Your name, please?", Login))
    assert digest != _question_digest(Elicit("Name?", Confirm))
    # A 16-byte sha256 prefix, base64url without padding.
    assert len(digest) == 22 and "=" not in digest


def test_state_round_trips_question_digests_at_v3():
    # v2 carries digests for every action and round-trips exactly; v1 (mid rolling deploy) reads as no progress.
    entries = {
        "a": _StateEntry(action="accept", data={"username": "octocat"}, q="qa"),
        "b": _StateEntry(action="decline", q="qb"),
        "c": _StateEntry(action="cancel", q="qc"),
    }
    encoded = _encode_state(entries, {})
    assert json.loads(encoded)["v"] == 3
    assert _decode_state(encoded).outcomes == entries
    v1 = json.dumps({"v": 1, "outcomes": {"a": {"action": "decline"}}})
    assert _decode_state(v1).outcomes == {}


@pytest.mark.anyio
async def test_restored_answer_with_matching_digest_completes_without_reasking():
    mcp = MCPServer(name="PinHappyPath", request_state_security=RequestStateSecurity.ephemeral())

    async def who(ctx: Context) -> Elicit[Login]:
        return Elicit("Who?", Login)

    async def check(login: Annotated[Login, Resolve(who)]) -> Elicit[Confirm]:
        return Elicit(f"Go as {login.username}?", Confirm)

    @mcp.tool()
    async def act(
        login: Annotated[Login, Resolve(who)],
        confirm: Annotated[Confirm, Resolve(check)],
    ) -> str:
        return f"{login.username}:{confirm.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert set(first.input_requests) == {_wire_key(who)}

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(who): ElicitResult(action="accept", content={"username": "octocat"})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        # Only the dependent question; the stored answer holds, "Who?" is not re-asked.
        assert set(second.input_requests) == {_wire_key(check)}

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(check): ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat:True"


@pytest.mark.anyio
async def test_restored_entry_is_repersisted_with_its_question_digest_intact():
    # A restored entry must ride into the next round's state digest-intact, or it would be re-asked next round.
    mcp = MCPServer(name="RepersistPin", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def who(ctx: Context) -> Elicit[Login]:
        return Elicit("Who?", Login)

    async def check(login: Annotated[Login, Resolve(who)]) -> Elicit[Confirm]:
        return Elicit(f"Go as {login.username}?", Confirm)

    async def plan(confirm: Annotated[Confirm, Resolve(check)], ctx: Context) -> Elicit[Restock]:
        return Elicit("Restock too?", Restock)

    # The body never runs (a question always pends); a bare `...` costs no coverage.
    @mcp.tool()
    async def act(restock: Annotated[Restock, Resolve(plan)]) -> str: ...

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(who): ElicitResult(action="accept", content={"username": "octocat"})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        third = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(check): ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(third, InputRequiredResult)

    round_two = _outcomes_on_the_wire(second.request_state)
    round_three = _outcomes_on_the_wire(third.request_state)
    # Accept entries are pinned to the exact rendered question they answered.
    assert round_two[_wire_key(who)]["q"] == _question_digest(Elicit("Who?", Login))
    assert round_three[_wire_key(check)]["q"] == _question_digest(Elicit("Go as octocat?", Confirm))
    assert round_three[_wire_key(who)] == round_two[_wire_key(who)]


@pytest.mark.anyio
async def test_decline_and_cancel_entries_carry_the_question_digest():
    mcp = MCPServer(name="PinAllActions", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    async def ask_confirm(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Confirm?", Confirm)

    async def ask_restock(ctx: Context) -> Elicit[Restock]:
        return Elicit("Restock?", Restock)

    # The body never runs (a question always pends); a bare `...` costs no coverage.
    @mcp.tool()
    async def act(
        name: Annotated[ElicitationResult[Login], Resolve(ask_name)],
        confirm: Annotated[ElicitationResult[Confirm], Resolve(ask_confirm)],
        restock: Annotated[Restock, Resolve(ask_restock)],
    ) -> str: ...

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        # The third question stays unanswered, so the call pends and outcomes hit the wire.
        second = await client.session.call_tool(
            "act",
            {},
            input_responses={
                _wire_key(ask_name): ElicitResult(action="decline"),
                _wire_key(ask_confirm): ElicitResult(action="cancel"),
            },
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)

    outcomes = _outcomes_on_the_wire(second.request_state)
    assert outcomes[_wire_key(ask_name)]["action"] == "decline"
    assert outcomes[_wire_key(ask_name)]["q"] == _question_digest(Elicit("Name?", Login))
    assert outcomes[_wire_key(ask_confirm)]["action"] == "cancel"
    assert outcomes[_wire_key(ask_confirm)]["q"] == _question_digest(Elicit("Confirm?", Confirm))


@pytest.mark.anyio
async def test_state_entry_without_a_question_digest_is_dropped_and_reasked():
    # An entry with no digest cannot prove its question, so it reads as no progress and is re-asked.
    mcp = MCPServer(name="UnpinnedEntry", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def whoami(login: Annotated[Login, Resolve(ask)]) -> str:
        return login.username

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("whoami", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        (key,) = first.input_requests

        # Schema-valid accept data under the live key, but no "q" pin.
        entry = {"action": "accept", "data": {"username": "spooky"}}
        crafted = json.dumps({"v": 3, "outcomes": {key: entry}})
        second = await client.session.call_tool(
            "whoami",
            {},
            request_state=_sealed_state(crafted, tool="whoami", args={}, audience="UnpinnedEntry"),
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)  # re-asked, not honored and not an error
        assert second.input_requests is not None
        assert set(second.input_requests) == {key}
        assert _outcomes_on_the_wire(second.request_state) == {}  # the unpinned entry is dropped

        final = await client.session.call_tool(
            "whoami",
            {},
            input_responses={key: ElicitResult(action="accept", content={"username": "octocat"})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat"


@pytest.mark.anyio
async def test_reworded_question_drops_the_stored_answer_and_reasks():
    # An answer holds only while its question is byte-identical: a reword (redeploy) drops it and re-asks.
    mcp = MCPServer(name="RewordAccept", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))
    wording = {"deploy": "Deploy to prod?"}

    async def ask_deploy(ctx: Context) -> Elicit[Confirm]:
        return Elicit(wording["deploy"], Confirm)

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    @mcp.tool()
    async def act(
        deploy: Annotated[Confirm, Resolve(ask_deploy)],
        name: Annotated[Login, Resolve(ask_name)],
    ) -> str:
        return f"{deploy.ok}:{name.username}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_deploy): ElicitResult(action="accept", content={"ok": True})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert _outcomes_on_the_wire(second.request_state)[_wire_key(ask_deploy)]["q"] == _question_digest(
            Elicit("Deploy to prod?", Confirm)
        )

        wording["deploy"] = "Deploy to staging?"

        third = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_name): ElicitResult(action="accept", content={"username": "octocat"})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        # The stale answer is dropped and the reworded question is asked, not an error.
        assert isinstance(third, InputRequiredResult)
        assert third.input_requests is not None
        assert set(third.input_requests) == {_wire_key(ask_deploy)}
        question = third.input_requests[_wire_key(ask_deploy)].params
        assert isinstance(question, ElicitRequestFormParams)
        assert question.message == "Deploy to staging?"
        # The sibling answer recorded in the same state survives the drop.
        outcomes = _outcomes_on_the_wire(third.request_state)
        assert _wire_key(ask_deploy) not in outcomes
        assert outcomes[_wire_key(ask_name)]["action"] == "accept"

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_deploy): ElicitResult(action="accept", content={"ok": True})},
            request_state=third.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "True:octocat"


@pytest.mark.anyio
async def test_decline_of_a_reworded_question_does_not_suppress_the_new_question():
    # A decline pinned to the old wording must not suppress the reworded question.
    mcp = MCPServer(name="RewordDecline", request_state_security=RequestStateSecurity.ephemeral())
    wording = {"q": "Use defaults?"}

    async def ask(ctx: Context) -> Elicit[Confirm]:
        return Elicit(wording["q"], Confirm)

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    @mcp.tool()
    async def act(
        choice: Annotated[ElicitationResult[Confirm], Resolve(ask)],
        name: Annotated[Login, Resolve(ask_name)],
    ) -> str:
        kind = "accepted" if isinstance(choice, AcceptedElicitation) else "declined"
        return f"{kind}:{name.username}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask): ElicitResult(action="decline")},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)

        wording["q"] = "Use the new defaults?"

        third = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_name): ElicitResult(action="accept", content={"username": "octocat"})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        # The stale decline is dropped and the reworded question is asked again.
        assert isinstance(third, InputRequiredResult)
        assert third.input_requests is not None
        assert set(third.input_requests) == {_wire_key(ask)}
        question = third.input_requests[_wire_key(ask)].params
        assert isinstance(question, ElicitRequestFormParams)
        assert question.message == "Use the new defaults?"

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask): ElicitResult(action="accept", content={"ok": True})},
            request_state=third.request_state,
            allow_input_required=True,
        )
        # Accepting the new question proves the old decline did not stick.
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "accepted:octocat"


@pytest.mark.anyio
async def test_reworded_question_reasks_even_when_the_answer_first_arrives():
    # The pend round records each question's digest in the state, so an answer that
    # first arrives after a reword (redeploy between ask and retry) re-asks instead
    # of being consumed as consent to the new wording.
    mcp = MCPServer(name="RewordArrival", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))
    wording = {"deploy": "Deploy to prod?"}

    async def ask_deploy(ctx: Context) -> Elicit[Confirm]:
        return Elicit(wording["deploy"], Confirm)

    @mcp.tool()
    async def act(deploy: Annotated[Confirm, Resolve(ask_deploy)]) -> str:
        return f"deployed:{deploy.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        pended = json.loads(_unseal_inner(first.request_state))["asked"]
        assert pended == {_wire_key(ask_deploy): _question_digest(Elicit("Deploy to prod?", Confirm))}

        wording["deploy"] = "Deploy to staging?"

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_deploy): ElicitResult(action="accept", content={"ok": True})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        # The stale answer to the old wording is not consumed; the reworded question is asked.
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        question = second.input_requests[_wire_key(ask_deploy)].params
        assert isinstance(question, ElicitRequestFormParams)
        assert question.message == "Deploy to staging?"

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_deploy): ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "deployed:True"


@pytest.mark.anyio
async def test_an_answer_without_the_echoed_state_is_reasked_not_consumed():
    # Without the echoed state there is no record of which question the client was
    # shown, so an answer arriving stateless re-asks instead of being consumed.
    mcp = MCPServer(name="Stateless", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ask(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Proceed?", Confirm)

    @mcp.tool()
    async def act(go: Annotated[Confirm, Resolve(ask)]) -> str:
        return f"went:{go.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask): ElicitResult(action="accept", content={"ok": True})},
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask): ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "went:True"


@pytest.mark.anyio
async def test_recorded_answer_containing_a_lone_surrogate_survives_to_later_rounds():
    # The state encoder escapes lone surrogates, so the decoder must parse them back:
    # a recorded answer with one must restore on the next round, not silently re-ask.
    mcp = MCPServer(name="Surrogate", request_state_security=RequestStateSecurity(keys=[_PIN_KEY]))

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    async def ask_confirm(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Confirm?", Confirm)

    @mcp.tool()
    async def act(
        name: Annotated[Login, Resolve(ask_name)],
        go: Annotated[Confirm, Resolve(ask_confirm)],
    ) -> str:
        return f"{name.username}:{go.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)

        second = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_name): ElicitResult(action="accept", content={"username": "oc\ud800t"})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        # The surrogate-bearing answer is recorded; only the unanswered question remains.
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        assert set(second.input_requests) == {_wire_key(ask_confirm)}

        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask_confirm): ElicitResult(action="accept", content={"ok": True})},
            request_state=second.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "oc\ud800t:True"


@pytest.mark.anyio
async def test_resolver_elicitation_seals_and_completes_on_a_fully_default_server():
    # The headline default-posture invariant: a resolver tool on a bare MCPServer() -
    # no name, no security configuration - mints sealed state and completes the round.
    mcp = MCPServer()

    async def ask(ctx: Context) -> Elicit[Confirm]:
        return Elicit("Go?", Confirm)

    @mcp.tool()
    async def act(go: Annotated[Confirm, Resolve(ask)]) -> str:
        return f"went:{go.ok}"

    async with Client(mcp, elicitation_callback=_never) as client:
        first = await client.session.call_tool("act", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.request_state is not None
        assert first.request_state.startswith("v1.")
        final = await client.session.call_tool(
            "act",
            {},
            input_responses={_wire_key(ask): ElicitResult(action="accept", content={"ok": True})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "went:True"


# --- Sample / ListRoots markers ---


async def _sample_never(  # pragma: no cover - declares the capability; never invoked
    context: ClientRequestContext, params: CreateMessageRequestParams
) -> CreateMessageResult:
    raise AssertionError("should not be called")


async def _roots_never(context: ClientRequestContext) -> ListRootsResult:  # pragma: no cover - see _sample_never
    raise AssertionError("should not be called")


def _sample_capital(ctx: Context) -> Sample:
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text="Capital of France?"))],
        max_tokens=16,
    )


@pytest.mark.anyio
@pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_sample_resolver_injects_result(mode: Literal["legacy", "auto"]):
    # Marker-routed sampling must not fire the SEP-2577 deprecation warning on
    # either transport: the embedded/marker form is the 2026-blessed carrier.
    mcp = MCPServer(name="Sampler", request_state_security=RequestStateSecurity.ephemeral())
    prompts: list[str] = []

    async def sampler(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
        content = params.messages[0].content
        assert isinstance(content, TextContent)
        prompts.append(content.text)
        return CreateMessageResult(role="assistant", content=TextContent(type="text", text="Paris"), model="m")

    @mcp.tool()
    async def capital(answer: Annotated[CreateMessageResult, Resolve(_sample_capital)]) -> str:
        assert isinstance(answer.content, TextContent)
        return answer.content.text

    async with Client(mcp, mode=mode, sampling_callback=sampler) as client:
        assert await _text(client, "capital", {}) == "Paris"
    assert prompts == ["Capital of France?"]


@pytest.mark.anyio
@pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")
@pytest.mark.parametrize("mode", ["legacy", "auto"])
async def test_list_roots_resolver_injects_result(mode: Literal["legacy", "auto"]):
    mcp = MCPServer(name="Rooted", request_state_security=RequestStateSecurity.ephemeral())

    async def client_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=FileUrl("file:///workspace"))])

    def fetch_roots(ctx: Context) -> ListRoots:
        return ListRoots()

    @mcp.tool()
    async def workspace(roots: Annotated[ListRootsResult, Resolve(fetch_roots)]) -> str:
        return str(len(roots.roots))

    async with Client(mcp, mode=mode, list_roots_callback=client_roots) as client:
        assert await _text(client, "workspace", {}) == "1"


@pytest.mark.anyio
async def test_mixed_kinds_batch_into_one_round():
    mcp = MCPServer(name="Mixed", request_state_security=RequestStateSecurity.ephemeral())

    async def ask_name(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    async def fetch_roots(ctx: Context) -> ListRoots:
        return ListRoots()

    @mcp.tool()
    async def combo(
        login: Annotated[Login, Resolve(ask_name)],
        answer: Annotated[CreateMessageResult, Resolve(_sample_capital)],
        roots: Annotated[ListRootsResult, Resolve(fetch_roots)],
    ) -> str:
        assert isinstance(answer.content, TextContent)
        return f"{login.username}/{answer.content.text}/{len(roots.roots)}"

    async with Client(
        mcp, elicitation_callback=_never, sampling_callback=_sample_never, list_roots_callback=_roots_never
    ) as client:
        first = await client.session.call_tool("combo", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        # All three kinds are asked together in a single round.
        kinds = sorted(type(req).__name__ for req in first.input_requests.values())
        assert kinds == ["CreateMessageRequest", "ElicitRequest", "ListRootsRequest"]
        responses: InputResponses = {}
        for key, req in first.input_requests.items():
            if isinstance(req, ElicitRequest):
                responses[key] = ElicitResult(action="accept", content={"username": "octocat"})
            elif isinstance(req, CreateMessageRequest):
                responses[key] = CreateMessageResult(
                    role="assistant", content=TextContent(type="text", text="hey"), model="m"
                )
            else:
                responses[key] = ListRootsResult(roots=[])
        final = await client.session.call_tool(
            "combo", {}, input_responses=responses, request_state=first.request_state, allow_input_required=True
        )
        assert isinstance(final, CallToolResult)
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "octocat/hey/0"


@pytest.mark.anyio
async def test_sampling_tool_without_client_capability_is_a_protocol_error():
    mcp = MCPServer(name="NoSamplingCapability", request_state_security=RequestStateSecurity.ephemeral())

    @mcp.tool()
    async def capital(answer: Annotated[CreateMessageResult, Resolve(_sample_capital)]) -> str:
        return "unreachable"  # pragma: no cover

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.call_tool("capital", {}, allow_input_required=True)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data is not None
    assert "sampling" in exc_info.value.error.data["requiredCapabilities"]


@pytest.mark.anyio
async def test_roots_tool_without_client_capability_is_a_protocol_error():
    mcp = MCPServer(name="NoRootsCapability", request_state_security=RequestStateSecurity.ephemeral())

    def fetch_roots(ctx: Context) -> ListRoots:
        return ListRoots()

    @mcp.tool()
    async def workspace(roots: Annotated[ListRootsResult, Resolve(fetch_roots)]) -> str:
        return "unreachable"  # pragma: no cover

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.call_tool("workspace", {}, allow_input_required=True)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data is not None
    assert "roots" in exc_info.value.error.data["requiredCapabilities"]


@pytest.mark.anyio
async def test_legacy_eliciting_tool_without_capability_is_a_protocol_error():
    # The 2025 back-channel leg enforces the same egress gate as `input_requests`:
    # a client that never declared elicitation gets -32021 instead of a request it
    # cannot handle, and the session keeps working afterwards.
    mcp = MCPServer(name="LegacyGate", request_state_security=RequestStateSecurity.ephemeral())

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def tool(login: Annotated[Login, Resolve(ask)]) -> str:
        return login.username  # pragma: no cover

    @mcp.tool()
    def plain() -> str:
        return "ok"

    async with Client(mcp, mode="legacy") as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("tool", {})
        assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
        assert await _text(client, "plain", {}) == "ok"


def _ask_with_tools(ctx: Context) -> Sample:
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text="2+2?"))],
        max_tokens=16,
        tools=[SamplingTool(name="calc", input_schema={"type": "object"})],
    )


def _ask_with_tool_choice(ctx: Context) -> Sample:
    return Sample(
        [SamplingMessage(role="user", content=TextContent(type="text", text="2+2?"))],
        max_tokens=16,
        tool_choice=ToolChoice(mode="none"),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("ask", [_ask_with_tools, _ask_with_tool_choice])
async def test_sample_tools_require_the_tools_subcapability(ask: Callable[[Context], Sample]):
    # Either `tools` or `tool_choice` on the marker demands `sampling.tools`, and the
    # refusal names the full requirement so the client can remediate in one step.
    mcp = MCPServer(name="NoToolsSubcapability", request_state_security=RequestStateSecurity.ephemeral())

    @mcp.tool()
    async def calc(answer: Annotated[CreateMessageResultWithTools, Resolve(ask)]) -> str:
        return "unreachable"  # pragma: no cover

    # The callback declares base `sampling` but not `sampling.tools`.
    async with Client(mcp, sampling_callback=_sample_never) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.session.call_tool("calc", {}, allow_input_required=True)
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data is not None
    assert exc_info.value.error.data["requiredCapabilities"] == {"sampling": {"tools": {}}}


@pytest.mark.anyio
async def test_sample_with_tools_round_trips_with_declared_subcapability():
    mcp = MCPServer(name="ToolsSampling", request_state_security=RequestStateSecurity.ephemeral())

    async def sampler(
        context: ClientRequestContext, params: CreateMessageRequestParams
    ) -> CreateMessageResultWithTools:
        assert params.tools is not None and params.tools[0].name == "calc"
        return CreateMessageResultWithTools(role="assistant", content=[TextContent(type="text", text="4")], model="m")

    @mcp.tool()
    async def calc(answer: Annotated[CreateMessageResultWithTools, Resolve(_ask_with_tools)]) -> str:
        assert isinstance(answer.content, list) and isinstance(answer.content[0], TextContent)
        return answer.content[0].text

    async with Client(
        mcp,
        sampling_callback=sampler,
        sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability()),
    ) as client:
        assert await _text(client, "calc", {}) == "4"


@pytest.mark.anyio
async def test_no_tool_use_answer_to_a_tools_request_is_accepted():
    # A model may legally answer a tools request without using a tool; the wire
    # payload then parses out of the response union as the plain result shape.
    # The answer must still validate and inject as `CreateMessageResultWithTools`.
    mcp = MCPServer(name="NoToolUse", request_state_security=RequestStateSecurity.ephemeral())

    @mcp.tool()
    async def calc(answer: Annotated[CreateMessageResultWithTools, Resolve(_ask_with_tools)]) -> str:
        assert isinstance(answer, CreateMessageResultWithTools)
        assert isinstance(answer.content, TextContent)
        return answer.content.text

    async with Client(
        mcp,
        sampling_callback=_sample_never,
        sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability()),
    ) as client:
        first = await client.session.call_tool("calc", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        (key,) = first.input_requests
        final = await client.session.call_tool(
            "calc",
            {},
            input_responses={
                key: CreateMessageResult(role="assistant", content=TextContent(type="text", text="4"), model="m")
            },
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert not final.is_error
        assert isinstance(final.content[0], TextContent)
        assert final.content[0].text == "4"


@pytest.mark.anyio
async def test_sample_outcome_persists_across_rounds():
    # A dependent chain forces three rounds; the client's LLM is sampled exactly
    # once and later rounds restore the recorded result from `request_state`.
    mcp = MCPServer(name="Chain", request_state_security=RequestStateSecurity.ephemeral())
    samples = 0

    async def sampler(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
        nonlocal samples
        samples += 1
        return CreateMessageResult(role="assistant", content=TextContent(type="text", text="Paris"), model="m")

    async def confirm(
        answer: Annotated[CreateMessageResult, Resolve(_sample_capital)], ctx: Context
    ) -> Elicit[Confirm]:
        return Elicit("Accept the model's answer?", Confirm)

    @mcp.tool()
    async def tool(
        ok: Annotated[Confirm, Resolve(confirm)],
        answer: Annotated[CreateMessageResult, Resolve(_sample_capital)],
    ) -> str:
        assert isinstance(answer.content, TextContent)
        return f"{answer.content.text}:{ok.ok}"

    async with Client(mcp, sampling_callback=sampler, elicitation_callback=_accept({"ok": True})) as client:
        assert await _text(client, "tool", {}) == "Paris:True"
    assert samples == 1


@pytest.mark.anyio
async def test_wrong_kind_response_for_sample_raises():
    mcp = MCPServer(name="WrongKind", request_state_security=RequestStateSecurity.ephemeral())

    @mcp.tool()
    async def capital(answer: Annotated[CreateMessageResult, Resolve(_sample_capital)]) -> str:
        return "unreachable"  # pragma: no cover

    async with Client(mcp, sampling_callback=_sample_never) as client:
        first = await client.session.call_tool("capital", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        (key,) = first.input_requests
        final = await client.session.call_tool(
            "capital",
            {},
            input_responses={key: ElicitResult(action="accept", content={"x": "y"})},
            request_state=first.request_state,
            allow_input_required=True,
        )
        assert isinstance(final, CallToolResult)
        assert final.is_error
        assert isinstance(final.content[0], TextContent)
        assert "wrong kind" in final.content[0].text


def test_mixed_marker_arms_raise_at_registration():
    async def ambiguous(ctx: Context) -> Sample | Elicit[Login]:
        raise NotImplementedError  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(ambiguous)]) -> str:
        return login.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="multiple Elicit/Sample/ListRoots arms"):
        Tool.from_function(tool)


def test_marker_union_with_generic_alias_member_registers():
    # `dict[str, Any]` passes `isinstance(c, type)` on Python 3.10; the arm filter
    # must not feed it to `issubclass`.
    async def maybe_ask(ctx: Context) -> Sample | dict[str, Any]:
        raise NotImplementedError  # pragma: no cover

    async def tool(answer: Annotated[CreateMessageResult, Resolve(maybe_ask)]) -> str:
        return "ok"  # pragma: no cover

    Tool.from_function(tool)


def test_decline_entry_for_a_sample_marker_is_invalid():
    # Only elicitations have decline/cancel outcomes; a decline entry consulted by a
    # Sample marker fails validation (data is None) and is dropped for a re-ask.
    with pytest.raises(ValidationError):
        _outcome_from_state(_StateEntry(action="decline"), _sample_capital(cast(Context, None)))
