"""The 2026-07-28 multi-round-trip request (MRTR) core pattern over tools/call.

A tool that needs more input answers with an ``input_required`` result; the client driver fulfils
the embedded requests through its registered callbacks and retries the original call carrying the
collected ``inputResponses`` and the echoed opaque ``requestState``. The fixture-driven tests pin
the driver's user-facing contract on both 2026 matrix cells; the wire-level tests record JSON-RPC
frames at the client transport seam over the modern streamable HTTP entry -- the only transport
serving 2026 JSON-RPC frames -- because retry ids and serialized key presence are protocol facts
invisible to API callers (the in-memory 2026 path has no JSON-RPC framing at all).
"""

from typing import Any

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    JSONRPCRequest,
    JSONRPCResponse,
    TextContent,
)
from mcp_types.version import LATEST_MODERN_VERSION

from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, Connect, mounted_app
from tests.interaction._helpers import RecordingTransport
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

# Deliberately not parseable as JSON or base64: a client that inspected or normalized
# request_state instead of echoing it byte-exact would fail the equality assertions below.
OPAQUE_STATE = 'state!{"not-json'

_NAME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _form_request(message: str) -> ElicitRequest:
    """A form-mode elicitation request embeddable in an InputRequiredResult's input_requests."""
    return ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=_NAME_SCHEMA))


def _login_server(request_states: list[str | None]) -> Server:
    """The two-round write-once server the roundtrip pair shares.

    Round 1 answers with one embedded form request plus the opaque state; round 2 asserts the
    byte-exact echo and completes with the elicited name. Every round's request_state is appended
    to `request_states`.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="login", input_schema={"type": "object"})])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "login"
        request_states.append(params.request_state)
        if params.input_responses is None:
            assert params.request_state is None
            return InputRequiredResult(
                input_requests={"github_login": _form_request("Provide your GitHub username")},
                request_state=OPAQUE_STATE,
            )
        assert params.request_state == OPAQUE_STATE
        answer = params.input_responses["github_login"]
        assert isinstance(answer, ElicitResult)
        assert answer.action == "accept"
        assert answer.content is not None
        return CallToolResult(content=[TextContent(text=f"hello {answer.content['name']}")])

    return Server("mrtr", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("mrtr:tools-call:write-once-roundtrip")
async def test_input_required_tool_call_is_auto_fulfilled_and_retried_to_completion(connect: Connect) -> None:
    """An input_required tools/call is fulfilled by the client driver and retried to completion.

    The registered callback answers the embedded form request and the retried call completes as a
    plain CallToolResult (spec basic workflow). The byte-exact requestState echo (spec MUST) is
    pinned by equality against a deliberately non-parseable literal -- the only observable proxy
    for the MUST NOT inspect/parse/modify rule; the retry's frame-level obligations are pinned by
    the wire test below.
    """
    request_states: list[str | None] = []
    server = _login_server(request_states)

    prompts: list[str] = []

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"name": "octocat"})

    async with connect(server, elicitation_callback=answer_login) as client:
        result = await client.call_tool("login", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="hello octocat")]))
    assert prompts == ["Provide your GitHub username"]
    # Exactly the initial round and one retry, the retry echoing the module constant byte-exact.
    assert request_states == [None, OPAQUE_STATE]


@requirement("mrtr:request-state-only:retry")
async def test_state_only_input_required_is_retried_with_no_responses_and_echoed_state(connect: Connect) -> None:
    """A state-only input_required result is retried with no inputResponses and the state echoed.

    There is nothing to dispatch, so no callbacks are registered -- a driver that wrongly
    dispatched on this branch would error the call instead of completing it. The spec's "MAY
    retry the original request immediately" is permission: the SDK paces the retry with an
    internal 50 ms backoff, its own pacing choice rather than a divergence, and the test neither
    adds sleeps nor asserts elapsed time.
    """
    resume_token = "resume-token-1"
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="resume", input_schema={"type": "object"})])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "resume"
        request_states.append(params.request_state)
        # Both rounds carry input_responses=None here, so the rounds are told apart by the state.
        if params.request_state is None:
            return InputRequiredResult(request_state=resume_token)
        assert params.request_state == resume_token
        assert params.input_responses is None
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("resumer", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("resume", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")]))
    # Exactly one retry, echoing the token the server minted.
    assert request_states == [None, resume_token]


# --- wire-level: the modern HTTP entry is the only 2026 framing seam ---


@requirement("mrtr:tools-call:write-once-roundtrip")
async def test_mrtr_retry_frame_carries_fresh_id_and_byte_exact_request_state() -> None:
    """The MRTR retry frame carries a fresh JSON-RPC id and the requestState key serialized byte-exact.

    Asserted at the client transport seam because the retry's id (spec MUST: initial request and
    retry are independent requests) and the serialized requestState key are invisible to API
    callers; the modern HTTP entry is the only transport serving 2026 JSON-RPC frames at this pin
    (the in-memory 2026 path has no framing). The recorded round-1 response also exhibits one
    compliant input_required interim -- enforcement of the at-least-one-of MUST is owned by its
    own entry -- and this test is the emission complement of the key-omission test below.
    """
    server = _login_server([])

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "octocat"})

    with anyio.fail_after(5):
        # One combined async-with, the recorder bound via := -- a separately nested `async with`
        # line mis-traces its exit arcs under branch coverage on 3.11+.
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer_login,
            ) as client,
        ):
            await client.call_tool("login", {})

    # Filtered to tools/call: the client's schema-cache refresh also puts a tools/list on the wire.
    calls = [
        message.message
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest) and message.message.method == "tools/call"
    ]
    assert len(calls) == 2
    first, retry = calls
    # Fresh id on the retry, asserted as inequality: the id *sequence* belongs to
    # protocol:request-id:unique, and pinned values would couple to the refresh-frame count.
    assert first.id is not None
    assert retry.id is not None
    assert retry.id != first.id
    assert first.params is not None
    assert "requestState" not in first.params
    assert "inputResponses" not in first.params
    assert retry.params is not None
    assert retry.params["requestState"] == OPAQUE_STATE
    assert retry.params["inputResponses"]["github_login"]["action"] == "accept"
    # The interim travelled as a *result*, matched to the initial request by its id (the received
    # log also carries the retry's response and the tools/list response).
    interim = next(
        message.message
        for message in recording.received
        if isinstance(message, SessionMessage)
        and isinstance(message.message, JSONRPCResponse)
        and message.message.id == first.id
    )
    assert interim.result["resultType"] == "input_required"
    assert "requestState" in interim.result


@requirement("mrtr:request-state:omitted-when-absent")
async def test_retry_omits_the_request_state_key_when_the_server_sent_none() -> None:
    """When the server's input_required carried no requestState, the retry omits the key entirely.

    The spec MUST NOT include one in the retry is wire-pinned: typed request_state None and
    key-absence are indistinguishable in-memory, so only the serialized retry frame can prove the
    omission. The fresh-id test above proves the same serializer emits the key when the server
    sent one, guarding this absence assertion against vacuity.
    """
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "ask"
        request_states.append(params.request_state)
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"q": _form_request("Need a name")})
        assert params.request_state is None
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("stateless-asker", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "ada"})

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer,
            ) as client,
        ):
            await client.call_tool("ask", {})

    calls = [
        message.message
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest) and message.message.method == "tools/call"
    ]
    assert len(calls) == 2
    retry = calls[1]
    assert retry.params is not None
    # The MUST NOT itself: no requestState key on the serialized retry...
    assert "requestState" not in retry.params
    # ...on a frame that is otherwise loaded -- the absence is specific, not a bare frame.
    assert "inputResponses" in retry.params
    # Handler-side corroboration of what the frame shows.
    assert request_states == [None, None]


@requirement("mrtr:request-state:scoped-to-originating-request")
async def test_parallel_mrtr_calls_keep_request_state_and_responses_isolated() -> None:
    """Parallel MRTR calls keep requestState and inputResponses scoped to their originating request.

    A symmetric rendezvous in the elicitation callback (each call sets its own round-1 event, then
    waits on the other's) forces both loops to be simultaneously mid-flight -- interim results
    received, neither retry sent -- before either retry leaves, so the spec scenario ("any other
    request that the client may be sending in parallel") provably occurs; the exhaustive scan over
    every recorded tools/call frame is the MUST NOT's proof that neither call's fields leak into
    the other's.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(
            tools=[
                types.Tool(name="alpha", input_schema={"type": "object"}),
                types.Tool(name="beta", input_schema={"type": "object"}),
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name in ("alpha", "beta")
        name = params.name
        if params.input_responses is None:
            return InputRequiredResult(
                input_requests={f"q-{name}": _form_request(f"for {name}")},
                request_state=f"state-{name}",
            )
        # Each retry carries its own call's state -- the handler-side half of the isolation claim.
        assert params.request_state == f"state-{name}"
        return CallToolResult(content=[TextContent(text=name)])

    server = Server("parallel", on_list_tools=list_tools, on_call_tool=call_tool)

    round1_seen = {"alpha": anyio.Event(), "beta": anyio.Event()}

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        name = params.message.removeprefix("for ")
        assert name in round1_seen
        # Symmetric rendezvous: set own round-1 event before waiting on the other's -- deadlock-free
        # by set-before-wait, and both loops are provably mid-flight before either retry leaves.
        round1_seen[name].set()
        other = "beta" if name == "alpha" else "alpha"
        with anyio.fail_after(5):
            await round1_seen[other].wait()
        return ElicitResult(action="accept", content={"name": name})

    results: dict[str, CallToolResult] = {}

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer,
            ) as client,
            # Last item so it exits first: both calls complete while the client is still open.
            anyio.create_task_group() as task_group,
        ):

            async def call(name: str) -> None:
                results[name] = await client.call_tool(name, {})

            task_group.start_soon(call, "alpha")
            task_group.start_soon(call, "beta")

    frames = [
        message.message
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest) and message.message.method == "tools/call"
    ]
    by_name: dict[str, list[dict[str, Any]]] = {"alpha": [], "beta": []}
    for frame in frames:
        assert frame.params is not None
        by_name[frame.params["name"]].append(frame.params)
    for name, sent_params in by_name.items():
        assert len(sent_params) == 2
        initial, retry = sent_params
        assert "requestState" not in initial
        assert "inputResponses" not in initial
        assert retry["requestState"] == f"state-{name}"
        assert set(retry["inputResponses"]) == {f"q-{name}"}
    # The exhaustive negative (spec MUST NOT): no recorded tools/call frame anywhere carries the
    # other call's state or responses.
    for params in (frame.params for frame in frames):
        assert params is not None
        other = "beta" if params["name"] == "alpha" else "alpha"
        assert params.get("requestState") in (None, f"state-{params['name']}")
        assert f"q-{other}" not in params.get("inputResponses", {})
    assert results == {
        "alpha": CallToolResult(content=[TextContent(text="alpha")]),
        "beta": CallToolResult(content=[TextContent(text="beta")]),
    }
