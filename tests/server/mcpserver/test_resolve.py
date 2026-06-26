"""Tests for resolver dependency injection (MRTR) on MCPServer tools."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Literal

import pytest
from mcp_types import (
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
from mcp.server.mcpserver.resolve import (
    _decode_state,
    _elicit_return_schema,
    _encode_state,
    _outcome_from_state,
    _resolver_key,
    find_resolved_parameters,
    uses_input_required,
)
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


async def _drive_mrtr(
    client: Client,
    tool: str,
    args: dict[str, object],
    answer: Callable[[str, ElicitRequestFormParams], ElicitResult],
    max_rounds: int = 10,
) -> CallToolResult:
    """Drive the 2026-07-28 `input_required` loop to completion.

    Re-invokes `tools/call` with `input_responses`/`request_state` until the
    server returns a final `CallToolResult`, fulfilling each pending request via
    `answer(key, request_params)`.
    """
    responses: InputResponses | None = None
    state: str | None = None
    for _ in range(max_rounds):
        result = await client.call_tool(
            tool, args, input_responses=responses, request_state=state, allow_input_required=True
        )
        if isinstance(result, CallToolResult):
            return result
        assert isinstance(result, InputRequiredResult)
        assert result.input_requests is not None
        responses = {}
        for key, req in result.input_requests.items():
            assert isinstance(req.params, ElicitRequestFormParams)
            responses[key] = answer(key, req.params)
        state = result.request_state
    raise AssertionError("input_required loop did not converge")  # pragma: no cover


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

    async with Client(mcp) as client:  # mode="auto" negotiates 2026-07-28
        assert client.session.protocol_version == "2026-07-28"
        result = await client.call_tool("delete_folder", {"path": "/docs"}, allow_input_required=True)
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
    mcp, fs = _delete_folder_server()
    fs["/docs"] = ["a.txt", "b.txt"]

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        assert "/docs has 2 file(s)" in params.message
        return ElicitResult(action=action, content=content)

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "delete_folder", {"path": "/docs"}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == expected
    assert ("/docs" in fs) is (expected != "deleted /docs")


@pytest.mark.anyio
async def test_input_required_empty_folder_completes_in_one_round():
    mcp, fs = _delete_folder_server()
    fs["/empty"] = []

    def never(key: str, params: ElicitRequestParams) -> ElicitResult:  # pragma: no cover
        raise AssertionError("should not elicit for an empty folder")

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "delete_folder", {"path": "/empty"}, never)
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

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        if "Username" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "act", {}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"

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

    async with Client(mcp) as client:
        # Both independent resolvers are asked together in the first round.
        first = await client.call_tool("both", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert len(first.input_requests) == 2

        result = await _drive_mrtr(client, "both", {}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"


def test_uses_input_required_version_gate():
    assert uses_input_required("2026-07-28") is True
    assert uses_input_required("2025-11-25") is False
    assert uses_input_required(None) is False


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
    outcomes: dict[str, ElicitationResult[BaseModel]] = {
        "a": AcceptedElicitation(data=Login(username="octocat")),
        "b": DeclinedElicitation(),
        "c": CancelledElicitation(),
        "d": AcceptedElicitation.model_construct(data="raw-token"),  # non-model value
    }
    decoded = _decode_state(_encode_state(outcomes))

    accepted = _outcome_from_state(decoded["a"], Login)
    assert isinstance(accepted, AcceptedElicitation) and accepted.data == Login(username="octocat")
    assert isinstance(_outcome_from_state(decoded["b"], None), DeclinedElicitation)
    assert isinstance(_outcome_from_state(decoded["c"], None), CancelledElicitation)
    raw = _outcome_from_state(decoded["d"], None)
    assert isinstance(raw, AcceptedElicitation) and raw.data == "raw-token"


def test_elicit_return_schema_extraction():
    assert _elicit_return_schema(Elicit[Login]) is Login  # bare Elicit[T]
    assert _elicit_return_schema(Login | Elicit[Login]) is Login  # union arm
    assert _elicit_return_schema(Login) is None  # no Elicit arm
    assert _elicit_return_schema(None) is None


@pytest.mark.anyio
async def test_non_elicitation_response_raises():
    mcp = MCPServer(name="WrongResponse")

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("Name?", Login)

    @mcp.tool()
    async def tool(name: Annotated[Login, Resolve(ask)]) -> str:
        return name.username  # pragma: no cover

    async with Client(mcp) as client:
        r1 = await client.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(r1, InputRequiredResult)
        assert r1.input_requests is not None
        (key,) = r1.input_requests
        # Answer with a sampling result instead of an elicitation result.
        r2 = await client.call_tool(
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

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "act", {}, answer)
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

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        if "user" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        assert "as octocat?" in params.message  # proves login was a real model
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "act", {}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"


@pytest.mark.anyio
async def test_accept_with_no_content_is_an_error_not_a_cancel():
    mcp = MCPServer(name="AcceptNoContent")

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit("user?", Login)

    @mcp.tool()
    async def tool(login: Annotated[Login, Resolve(ask)]) -> str:
        return login.username  # pragma: no cover

    async with Client(mcp) as client:
        r1 = await client.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(r1, InputRequiredResult)
        assert r1.input_requests is not None
        (key,) = r1.input_requests
        r2 = await client.call_tool(
            "tool",
            {},
            input_responses={key: ElicitResult(action="accept", content=None)},
            request_state=r1.request_state,
            allow_input_required=True,
        )
        assert isinstance(r2, CallToolResult)
        assert r2.is_error
        assert isinstance(r2.content[0], TextContent)
        assert "no content" in r2.content[0].text


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

    async with Client(mcp) as client:
        first = await client.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert len(first.input_requests) == 2  # batched, not serialized

        result = await _drive_mrtr(client, "tool", {}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"


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

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        nonlocal a_asks
        if "name" in params.message:
            a_asks += 1
            return ElicitResult(action="accept", content={"username": "octocat"})
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "tool", {}, answer)
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

    async with Client(mcp) as client:
        first = await client.call_tool("tool", {}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        assert first.input_requests is not None
        assert len(first.input_requests) == 2  # distinct keys, not collapsed to one

        result = await _drive_mrtr(client, "tool", {}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "A,B"


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

    def answer(key: str, params: ElicitRequestFormParams) -> ElicitResult:
        if "user" in params.message:
            return ElicitResult(action="accept", content={"username": "octocat"})
        assert "as octocat?" in params.message  # login restored as a real model
        return ElicitResult(action="accept", content={"ok": True})

    async with Client(mcp) as client:
        result = await _drive_mrtr(client, "act", {}, answer)
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == "octocat:True"


def test_wire_key_is_worker_stable_for_methods_and_callable_objects():
    from mcp.server.mcpserver.resolve import _state_key

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
