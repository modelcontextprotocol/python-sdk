"""Tests for resolver dependency injection (MRTR) on MCPServer tools."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

import anyio
import pytest
from mcp_types import (
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    CallToolResult,
    CreateMessageResult,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    InputRequiredResult,
    InputResponses,
    TextContent,
)
from pydantic import BaseModel, Field

from mcp import Client, InputRequiredRoundsExceededError
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
from mcp.server.mcpserver.resolve import (
    _decode_state,
    _elicit_return_schema,
    _encode_state,
    _outcome_from_state,
    _resolver_key,
    _state_key,
    _StateEntry,
    _uses_input_required,
    find_resolved_parameters,
)
from mcp.server.mcpserver.tools.base import Tool
from mcp.shared.exceptions import MCPError


class Login(BaseModel):
    username: str


class Confirm(BaseModel):
    ok: bool


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


def test_multiple_elicit_arms_raise_at_registration():
    # The runtime can honor only one static question schema per resolver, so an
    # ambiguous `-> Elicit[A] | Elicit[B]` must not register (the second arm used
    # to be silently ignored).
    async def ambiguous(ctx: Context) -> Elicit[Login] | Elicit[Confirm]:
        raise NotImplementedError  # pragma: no cover

    async def tool(login: Annotated[Login, Resolve(ambiguous)]) -> str:
        return login.username  # pragma: no cover

    with pytest.raises(InvalidSignature, match="multiple Elicit arms"):
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


def _delete_folder_server() -> tuple[MCPServer, dict[str, list[str]]]:
    """The `delete_folder` example from docs/migration.md, wired to an in-memory fs."""
    mcp = MCPServer(name="files")
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
async def test_input_required_resolver_asks_and_consumes_then_never_reruns():
    mcp = MCPServer(name="ExactlyOnceMRTR")
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
    # An eliciting resolver runs twice - once to ask, once to consume the answer -
    # then its outcome is carried in `request_state` and it never runs again. `login`
    # asks in round 1 and is consumed in round 2; `confirm` (which depends on
    # `login`) only forms its question once `login` is known, so it asks in round 2
    # and is consumed in round 3. Neither re-runs beyond consuming its own answer.
    assert counts == {"login": 2, "confirm": 2}


@pytest.mark.anyio
async def test_input_required_batches_independent_elicits_in_one_round():
    mcp = MCPServer(name="BatchedMRTR")

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
    mcp = MCPServer(name="AutoBatch")
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
    assert _decode_state(request_state) == {}


def test_state_round_trips_accept_decline_cancel():
    entries = {
        "a": _StateEntry(action="accept", data={"username": "octocat"}),
        "b": _StateEntry(action="decline"),
        "c": _StateEntry(action="cancel"),
        "d": _StateEntry(action="accept", data="raw-token"),  # non-dict wire value
    }
    decoded = _decode_state(_encode_state(entries))
    assert decoded == entries  # encode-restore is the identity on the stored entries

    accepted = _outcome_from_state(decoded["a"], Login)
    assert isinstance(accepted, AcceptedElicitation) and accepted.data == Login(username="octocat")
    assert isinstance(_outcome_from_state(decoded["b"], None), DeclinedElicitation)
    assert isinstance(_outcome_from_state(decoded["c"], None), CancelledElicitation)
    raw = _outcome_from_state(decoded["d"], None)
    assert isinstance(raw, AcceptedElicitation) and raw.data == "raw-token"


def test_elicit_return_schema_extraction():
    assert _elicit_return_schema(Elicit[Login], "r") is Login  # bare Elicit[T]
    assert _elicit_return_schema(Login | Elicit[Login], "r") is Login  # union arm
    assert _elicit_return_schema(Login, "r") is None  # no Elicit arm
    assert _elicit_return_schema(None, "r") is None
    # The bound on `Elicit`'s parameter is unenforced at runtime, so a non-model
    # subscription is constructible and must yield no schema rather than crash.
    unbounded_elicit: Any = Elicit
    assert _elicit_return_schema(unbounded_elicit[int], "r") is None
    # Two distinct Elicit arms are ambiguous: the runtime can honor only one schema.
    with pytest.raises(InvalidSignature, match="'r' return annotation has multiple Elicit arms"):
        _elicit_return_schema(Elicit[Login] | Elicit[Confirm], "r")


@pytest.mark.anyio
async def test_non_elicitation_response_raises():
    mcp = MCPServer(name="WrongResponse")

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
    mcp = MCPServer(name="Direct")

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
    mcp = MCPServer(name="Instances")

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
    mcp = MCPServer(name="NonSerializable")

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
    mcp = MCPServer(name="BareElicitDep")

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
    mcp = MCPServer(name="AcceptNoContent")

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
    mcp = MCPServer(name="NoElicitationCapability")

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
    mcp = MCPServer(name="NestedBatch")

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
    mcp = MCPServer(name="DeepChain")

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
    mcp = MCPServer(name="FactoryClosures")

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
    # A resolver annotated `-> Login` that actually returns `Elicit(...)` has no
    # `Elicit[T]` return arm, so `elicit_schema` is None. Its answer, restored from
    # request_state in a 3+ round flow, must still come back as a Login model (not a
    # raw dict) so a dependent resolver/tool can use its attributes.
    mcp = MCPServer(name="LyingAnnotation")

    # Annotated without an `Elicit[T]` return arm, so `elicit_schema` is None.
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
    mcp = MCPServer(name="DeclinePersists")

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
        assert _decode_state(second.request_state)[ra_key].action == "decline"

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
    # entries matching no resolver are tolerated (both are client-supplied), and the
    # ghost state entry is not echoed into any later round's `request_state`.
    mcp = MCPServer(name="GhostKeys")

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

        spliced = json.loads(first.request_state)
        spliced["outcomes"]["ghost"] = {"action": "accept", "data": {"username": "spooky"}}
        second = await client.session.call_tool(
            "act",
            {},
            input_responses={
                ra_key: ElicitResult(action="accept", content={"username": "octocat"}),
                "ghost": ElicitResult(action="accept", content={"username": "spooky"}),
            },
            request_state=json.dumps(spliced),
            allow_input_required=True,
        )
        assert isinstance(second, InputRequiredResult)
        assert second.input_requests is not None
        (rb_key,) = second.input_requests
        outcomes = _decode_state(second.request_state)
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
    # `request_state` is client-trusted JSON: an accept entry whose data does not
    # validate against the resolver's schema reads as no recorded progress, so the
    # question is asked again (not an error) and a proper answer completes the call.
    mcp = MCPServer(name="ForgedState")

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

        forged = json.loads(first.request_state)
        forged["outcomes"][key] = {"action": "accept", "data": forged_data}
        second = await client.session.call_tool(
            "whoami", {}, request_state=json.dumps(forged), allow_input_required=True
        )
        assert isinstance(second, InputRequiredResult)  # re-asked, not an error
        assert second.input_requests is not None
        assert set(second.input_requests) == {key}
        assert _decode_state(second.request_state) == {}  # the forged entry is dropped

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
    mcp = MCPServer(name="MismatchedAnswer")

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
    mcp = MCPServer(name="TooDeep")
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
    mcp = MCPServer(name="AliasState")

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
    mcp = MCPServer(name="DivergentAliases")

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
        assert _decode_state(second.request_state)[who_key].data == {"vUser": "octocat"}

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
