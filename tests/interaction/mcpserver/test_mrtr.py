"""Multi-round-trip authoring on MCPServer: resolver-injected parameters, input_required
pass-through for resources and prompts, and the default requestState sealing."""

from typing import Annotated

import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    CallToolResult,
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitRequestParams,
    ElicitResult,
    ErrorData,
    GetPromptResult,
    InputRequiredResult,
    InputResponses,
    ListRootsResult,
    PromptMessage,
    ReadResourceResult,
    Root,
    SamplingMessage,
    TextContent,
    TextResourceContents,
)
from pydantic import BaseModel, FileUrl

from mcp import MCPError
from mcp.client import ClientRequestContext
from mcp.server.mcpserver import Context, Elicit, ListRoots, MCPServer, Resolve, Sample
from tests._stamp import Unstamp
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

_CONFIRM = ElicitRequest(
    params=ElicitRequestFormParams(message="Confirm?", requested_schema={"type": "object", "properties": {}})
)
_CONFIRMED: InputResponses = {"ok": ElicitResult(action="accept", content={})}


class Login(BaseModel):
    username: str


@requirement("mcpserver:resolve:elicit")
async def test_a_resolver_elicited_argument_is_filled_from_the_elicitation_callback_on_every_era(
    connect: Connect, unstamped: Unstamp
) -> None:
    """SDK-defined: one tool body, no era branch. On 2026-07-28 the question travels as an
    input_required round trip; on 2025-11-25 as a server-to-client elicitation/create."""
    mcp = MCPServer("greeter")
    question = "GitHub username?"

    async def ask(ctx: Context) -> Elicit[Login]:
        return Elicit(question, Login)

    @mcp.tool()
    async def greet(login: Annotated[Login, Resolve(ask)]) -> str:
        return f"hello {login.username}"

    prompts: list[str] = []

    async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"username": "octocat"})

    async with connect(mcp, elicitation_callback=answer) as client:
        result = await client.call_tool("greet", {})

    assert prompts == [question]
    assert unstamped(result) == snapshot(
        CallToolResult(content=[TextContent(text="hello octocat")], structured_content={"result": "hello octocat"})
    )


@requirement("mcpserver:resolve:sample")
async def test_a_resolver_sample_request_is_answered_by_the_sampling_callback_on_every_era(
    connect: Connect, unstamped: Unstamp
) -> None:
    """SDK-defined: the resolver's Sample marker becomes a sampling request on whichever channel the
    era provides, and the CreateMessageResult is injected into the annotated parameter."""
    mcp = MCPServer("geographer")
    question = "Capital of France?"

    def ask_capital(ctx: Context) -> Sample:
        return Sample([SamplingMessage(role="user", content=TextContent(text=question))], max_tokens=16)

    @mcp.tool()
    async def capital(answer: Annotated[CreateMessageResult, Resolve(ask_capital)]) -> str:
        assert isinstance(answer.content, TextContent)
        return answer.content.text

    prompts: list[str] = []

    async def sample(context: ClientRequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
        content = params.messages[0].content
        assert isinstance(content, TextContent)
        prompts.append(content.text)
        return CreateMessageResult(role="assistant", content=TextContent(text="Paris"), model="m")

    async with connect(mcp, sampling_callback=sample) as client:
        result = await client.call_tool("capital", {})

    assert prompts == [question]
    assert unstamped(result) == snapshot(
        CallToolResult(content=[TextContent(text="Paris")], structured_content={"result": "Paris"})
    )


@requirement("mcpserver:resolve:list-roots")
async def test_a_resolver_roots_request_is_answered_by_the_roots_callback_on_every_era(
    connect: Connect, unstamped: Unstamp
) -> None:
    """SDK-defined: the resolver's ListRoots marker is answered by the client's roots callback and the
    ListRootsResult is injected into the annotated parameter, on both eras."""
    mcp = MCPServer("explorer")

    def fetch(ctx: Context) -> ListRoots:
        return ListRoots()

    @mcp.tool()
    async def workspace(roots: Annotated[ListRootsResult, Resolve(fetch)]) -> str:
        return ",".join(str(root.uri) for root in roots.roots)

    async def list_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=FileUrl("file:///workspace"))])

    async with connect(mcp, list_roots_callback=list_roots) as client:
        result = await client.call_tool("workspace", {})

    assert unstamped(result) == snapshot(
        CallToolResult(
            content=[TextContent(text="file:///workspace")], structured_content={"result": "file:///workspace"}
        )
    )


@requirement("resources:mrtr:read:basic")
async def test_a_template_resource_returning_input_required_is_read_again_with_the_answer(
    connect: Connect, unstamped: Unstamp
) -> None:
    """Spec-mandated (resources/read is MRTR-supported): a template function may return an
    InputRequiredResult; the retry's answer arrives on ctx.input_responses."""
    mcp = MCPServer("vault")

    @mcp.resource("secret://{name}")
    async def secret(name: str, ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            ask = ElicitRequestFormParams(
                message=f"PIN for {name}?",
                requested_schema={"type": "object", "properties": {"pin": {"type": "string"}}},
            )
            return InputRequiredResult(input_requests={"pin": ElicitRequest(params=ask)})
        answer = ctx.input_responses["pin"]
        assert isinstance(answer, ElicitResult)
        assert answer.content is not None
        return f"{name}:{answer.content['pin']}"

    prompts: list[str] = []

    async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"pin": "1234"})

    async with connect(mcp, elicitation_callback=answer) as client:
        result = await client.read_resource("secret://vault")

    assert prompts == ["PIN for vault?"]
    assert unstamped(result) == snapshot(
        ReadResourceResult(
            contents=[TextResourceContents(uri="secret://vault", mime_type="text/plain", text="vault:1234")]
        )
    )


@requirement("prompts:mrtr:get:basic")
async def test_a_prompt_returning_input_required_is_rendered_again_with_the_answer(
    connect: Connect, unstamped: Unstamp
) -> None:
    """Spec-mandated (prompts/get is MRTR-supported): a prompt function may return an
    InputRequiredResult; the retry's answer arrives on ctx.input_responses."""
    mcp = MCPServer("hr")

    @mcp.prompt()
    async def onboarding(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            ask = ElicitRequestFormParams(
                message="Team name?",
                requested_schema={"type": "object", "properties": {"team": {"type": "string"}}},
            )
            return InputRequiredResult(input_requests={"team": ElicitRequest(params=ask)})
        answer = ctx.input_responses["team"]
        assert isinstance(answer, ElicitResult)
        assert answer.content is not None
        return f"Welcome to {answer.content['team']}"

    prompts: list[str] = []

    async def answer(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"team": "platform"})

    async with connect(mcp, elicitation_callback=answer) as client:
        result = await client.get_prompt("onboarding")

    assert prompts == ["Team name?"]
    assert unstamped(result) == snapshot(
        GetPromptResult(
            description="", messages=[PromptMessage(role="user", content=TextContent(text="Welcome to platform"))]
        )
    )


def _shop() -> tuple[MCPServer, list[str | None]]:
    """A checkout tool that asks for confirmation once, remembering the cart in requestState.

    Returns the server and the `ctx.request_state` values the tool body saw, one per run.
    """
    mcp = MCPServer("shop")
    states: list[str | None] = []

    @mcp.tool()
    async def checkout(item: str, ctx: Context) -> str | InputRequiredResult:
        states.append(ctx.request_state)
        if ctx.request_state is None:
            return InputRequiredResult(input_requests={"ok": _CONFIRM}, request_state="cart:1")
        return f"bought {item}"

    return mcp, states


async def _never_elicit(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    raise NotImplementedError


@requirement("mrtr:request-state:reject-tampered")
async def test_a_tampered_request_state_is_rejected_before_the_tool_reruns(connect: Connect) -> None:
    """MCPServer seals requestState by default (the SDK's enforcement of the spec's integrity SHOULD): the
    client holds an opaque token, and an altered echo is refused with the frozen -32602 before the tool runs.

    The first round is taken by hand (as a client persisting the state would) so the test controls
    what the resumed call echoes back."""
    mcp, states = _shop()

    async with connect(mcp, elicitation_callback=_never_elicit) as client:
        first = await client.session.call_tool("checkout", {"item": "book"}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        sealed = first.request_state
        assert sealed is not None and sealed != "cart:1"
        # Flip one character; not the last, whose unused base64 bits can change without altering the token.
        tampered = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("checkout", {"item": "book"}, input_responses=_CONFIRMED, request_state=tampered)

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=INVALID_PARAMS, message="Invalid or expired requestState", data={"reason": "invalid_request_state"}
        )
    )
    assert states == [None]


@requirement("mrtr:request-state:replay-binding")
async def test_request_state_replayed_with_different_arguments_is_rejected(
    connect: Connect, unstamped: Unstamp
) -> None:
    """Spec-mandated replay protection, request-binding arm: the sealed state is bound to the
    originating call, so echoing it verbatim with other arguments is refused; the honest resume
    completes and the tool sees the plaintext state, never the sealed form."""
    mcp, states = _shop()

    async with connect(mcp, elicitation_callback=_never_elicit) as client:
        first = await client.session.call_tool("checkout", {"item": "book"}, allow_input_required=True)
        assert isinstance(first, InputRequiredResult)
        sealed = first.request_state
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("checkout", {"item": "tv"}, input_responses=_CONFIRMED, request_state=sealed)
        result = await client.call_tool("checkout", {"item": "book"}, input_responses=_CONFIRMED, request_state=sealed)

    assert exc_info.value.error == snapshot(
        ErrorData(
            code=INVALID_PARAMS, message="Invalid or expired requestState", data={"reason": "invalid_request_state"}
        )
    )
    assert unstamped(result) == snapshot(
        CallToolResult(content=[TextContent(text="bought book")], structured_content={"result": "bought book"})
    )
    assert states == [None, "cart:1"]
