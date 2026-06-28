"""SEP-2549 caching hints: producer-side stamping and the client-facing TTL/scope semantics.

The fixture-driven tests pin what the public Client surfaces on the era matrix; one test records
2026 JSON-RPC frames over the modern HTTP entry because absent-vs-default hint keys are invisible
to typed models; and one plays a non-conformant server by hand over memory streams because the
typed Server cannot author the malformed value under test. The client-side response-cache
behaviours (fresh windows, invalidation, cache keys) are deliberately absent: the SDK has no
response cache, and the manifest tracks each as a deferred `caching:*` entry that re-opens when
one lands.
"""

import anyio
import mcp_types as types
import pytest
from mcp_types import (
    DiscoverResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    Implementation,
    InputRequiredResult,
    JSONRPCRequest,
    JSONRPCResponse,
    ListPromptsResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    Prompt,
    ReadResourceResult,
    ResourceTemplate,
    ServerCapabilities,
    TextResourceContents,
    Tool,
)
from mcp_types.version import LATEST_MODERN_VERSION
from pydantic import ValidationError

from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, Connect, mounted_app
from tests.interaction._helpers import RecordingTransport
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

# Non-default on purpose (the defaults are 0/"private"): a result the server failed to stamp
# would surface the defaults, so only non-default values prove the authored hints travelled.
PROMPTS_TTL_MS = 60_000
TEMPLATES_TTL_MS = 120_000

_NAME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


@requirement("caching:hints:prompts-list")
async def test_prompts_list_result_carries_the_handler_authored_ttl_and_scope_hints(connect: Connect) -> None:
    """Handler-authored ttlMs/cacheScope on a prompts/list result reach the client unmodified, on
    a resultType complete result. Spec-mandated (draft server/utilities/caching, the six-operation
    MUST); the non-default values prove the hints travelled -- a result the server failed to stamp
    would surface the 0/private defaults. On the streamable-http cell the 2026 wire surface makes
    both hints required, so the client's own validation co-proves wire presence.
    """

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        assert params is not None  # the client always sends params, even without a cursor
        return ListPromptsResult(prompts=[Prompt(name="greet")], ttl_ms=PROMPTS_TTL_MS, cache_scope="public")

    server = Server("cached", on_list_prompts=list_prompts)

    async with connect(server) as client:
        result = await client.list_prompts()

    assert result.ttl_ms == PROMPTS_TTL_MS
    assert result.cache_scope == "public"
    assert result.result_type == "complete"
    assert result.prompts == [Prompt(name="greet")]


@requirement("caching:hints:resources-templates-list")
async def test_resource_templates_list_result_carries_the_handler_authored_ttl_and_scope_hints(
    connect: Connect,
) -> None:
    """Handler-authored ttlMs/cacheScope on a resources/templates/list result reach the client
    unmodified, on a resultType complete result. Spec-mandated (draft server/utilities/caching --
    the sixth operation of the six-operation MUST); the non-default values prove the hints
    travelled, and on the streamable-http cell the required 2026 wire aliases co-prove wire
    presence.
    """

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        assert params is not None  # the client always sends params, even without a cursor
        return ListResourceTemplatesResult(
            resource_templates=[ResourceTemplate(name="file", uri_template="file:///{name}")],
            ttl_ms=TEMPLATES_TTL_MS,
            cache_scope="public",
        )

    server = Server("cached", on_list_resource_templates=list_resource_templates)

    async with connect(server) as client:
        result = await client.list_resource_templates()

    assert result.ttl_ms == TEMPLATES_TTL_MS
    assert result.cache_scope == "public"
    assert result.result_type == "complete"
    assert result.resource_templates == [ResourceTemplate(name="file", uri_template="file:///{name}")]


@requirement("caching:pagination:same-scope-all-pages")
async def test_mismatched_per_page_cache_scopes_are_forwarded_unmodified_across_a_cursor_walk(
    connect: Connect,
) -> None:
    """A handler that authors cacheScope public on page 1 and private on page 2 of one cursor walk
    reaches the client unmodified on both pages: the SDK applies no cross-page cacheScope
    consistency, so the spec's same-scope-all-pages MUST rests entirely on the handler author.
    Pins the known gap recorded on the requirement (divergence); a future enforcing SDK fails this
    test -- re-pin to `page2.cache_scope == page1.cache_scope` and delete the Divergence.
    """
    seen_cursors: list[str | None] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        seen_cursors.append(params.cursor)
        if params.cursor is None:
            return ListToolsResult(
                tools=[Tool(name="a", input_schema={"type": "object"})],
                next_cursor="page-2",
                cache_scope="public",
            )
        assert params.cursor == "page-2"
        # Deliberately mismatched with page 1's "public": the forwarded mismatch is the pinned gap.
        return ListToolsResult(tools=[Tool(name="b", input_schema={"type": "object"})], cache_scope="private")

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        page1 = await client.list_tools()
        page2 = await client.list_tools(cursor=page1.next_cursor)

    assert page1.cache_scope == "public"
    assert page2.cache_scope == "private"
    # One request's page sequence, not two independent walks.
    assert seen_cursors == [None, "page-2"]


@requirement("caching:ttl:absent-defaults-zero")
async def test_a_result_without_ttl_from_a_2025_server_surfaces_the_immediately_stale_defaults(
    connect: Connect,
) -> None:
    """A 2025-era exchange carries no ttlMs/cacheScope on the wire (the
    hosting:http:legacy-no-modern-vocabulary entry pins the absence over HTTP); the client
    surfaces ttl_ms 0 -- immediately stale -- and the SDK's safe cacheScope default private. The
    ttl half is the spec SHOULD for older servers; the private half is SDK-defined (the spec
    sentence covers only ttlMs).
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        # Neither hint authored: the spec's "older server versions" scenario, not laziness --
        # authored hints would be dropped on the 2025 wire anyway.
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        result = await client.list_tools()

    assert result.ttl_ms == 0
    assert result.cache_scope == "private"
    assert [tool.name for tool in result.tools] == ["t"]


@requirement("caching:ttl:zero-immediately-stale")
async def test_ttl_zero_results_are_refetched_on_every_access(connect: Connect) -> None:
    """Two consecutive list_tools calls against a ttlMs-0 server both reach the handler: nothing
    is served from a cache. Honest provenance: this passes by construction -- the client has no
    response cache at all, so the identical observable would occur for any ttl (the positive-ttl
    fresh window is the deferred not-implemented sibling). The pin is the regression bar for a
    future cache: one that wrongly served a ttlMs-0 entry fails it.
    """
    fetches: list[int] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        fetches.append(1)
        # ttl_ms=0 authored explicitly: the value under test, not the default's accident.
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})], ttl_ms=0, cache_scope="public")

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        first = await client.list_tools()
        second = await client.list_tools()

    assert len(fetches) == 2
    # The stamped value really was the one under test on both fetches.
    assert first.ttl_ms == 0
    assert second.ttl_ms == 0


# --- wire-level: the modern HTTP entry is the only 2026 framing seam ---


@requirement("caching:input-required:no-hints")
@requirement("mrtr:input-required-result:result-type-serialized")
async def test_the_interim_input_required_frame_carries_no_caching_hints_while_the_complete_frame_does() -> None:
    """On one resources/read MRTR exchange, the serialized interim frame's result holds exactly
    inputRequests plus resultType input_required -- no ttlMs, no cacheScope -- while the terminal
    complete frame of the same method carries both. Asserted at the client transport seam over the
    modern HTTP entry because typed models hide absent-vs-default (the monolith would default-fill
    the hints on read-back); the in-test contrast frame guards the absence assertion against
    vacuity. Spec-mandated (draft server/utilities/caching: interim results are not cacheable and
    carry no caching hints), and the same key-set pin proves the resultType discriminator is
    serialized explicitly (the stacked mrtr entry). The unobservable consumer half ('are not
    cacheable') is recorded on the entry, not here.
    """

    async def read_resource(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> ReadResourceResult | InputRequiredResult:
        assert str(params.uri) == "res://profile"
        if params.input_responses is None:
            return InputRequiredResult(
                input_requests={
                    "who": ElicitRequest(params=ElicitRequestFormParams(message="Who?", requested_schema=_NAME_SCHEMA))
                }
            )
        answer = params.input_responses["who"]
        assert isinstance(answer, ElicitResult)
        assert answer.content is not None
        # Both hints authored non-default (the defaults are 0/"private"): the contrast frame is
        # provably handler-driven, not default fill.
        return ReadResourceResult(
            contents=[TextResourceContents(uri="res://profile", text=f"hi {answer.content['name']}")],
            ttl_ms=60_000,
            cache_scope="public",
        )

    server = Server("cached", on_read_resource=read_resource)

    async def answer_who(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "ada"})

    with anyio.fail_after(5):
        # One combined async-with, the recorder bound via := -- a separately nested `async with`
        # line mis-traces its exit arcs under branch coverage on 3.11+.
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer_who,
            ) as client,
        ):
            result = await client.read_resource("res://profile")

    # The whole sent log, not a filter: resources/read generates no implicit sibling traffic.
    reads = [message.message for message in recording.sent if isinstance(message.message, JSONRPCRequest)]
    assert [read.method for read in reads] == ["resources/read", "resources/read"]
    responses = {
        message.message.id: message.message.result
        for message in recording.received
        if isinstance(message, SessionMessage) and isinstance(message.message, JSONRPCResponse)
    }
    interim = responses[reads[0].id]
    complete = responses[reads[1].id]
    # Exact key vocabulary: a stronger absence claim than two `not in` checks -- any field added to
    # interim frames fails loudly -- and the explicit resultType value is the stacked entry's pin.
    assert sorted(interim) == ["inputRequests", "resultType"]
    assert interim["resultType"] == "input_required"
    # The same-exchange contrast frame: the terminal complete result of the same method carries both.
    assert complete["ttlMs"] == 60_000
    assert complete["cacheScope"] == "public"
    assert complete["resultType"] == "complete"
    # The typed surface agrees with the terminal frame.
    assert result.contents == [TextResourceContents(uri="res://profile", text="hi ada")]
    assert result.ttl_ms == 60_000


# --- scripted peer: a malformed inbound value the typed Server cannot author ---


@requirement("caching:ttl:negative-treated-as-zero")
async def test_a_negative_ttl_from_a_nonconformant_server_is_rejected_not_coerced_to_zero() -> None:
    """A tools/list answer carrying ttlMs -1 raises a pydantic ValidationError out of the awaiting
    call instead of being ignored and treated as 0 -- the spec SHOULD is not implemented (known
    gap recorded on the requirement: Field(ge=0) rejects before any leniency could run). The test
    plays the server by hand over memory streams because the typed Server cannot author a negative
    ttlMs (the same ge=0 constraint, at construction), and uses the bare pinned-2026 ClientSession
    because Client has no public connect path over raw scripted streams. When coerce-to-zero
    leniency lands, this test fails: re-pin to ttl_ms == 0 and delete the Divergence.
    """
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def scripted_server() -> None:
            with anyio.fail_after(5):
                incoming = await server_read.receive()
            assert isinstance(incoming, SessionMessage)
            assert isinstance(incoming.message, JSONRPCRequest)
            assert incoming.message.method == "tools/list"
            await server_write.send(
                SessionMessage(
                    JSONRPCResponse(
                        jsonrpc="2.0",
                        id=incoming.message.id,
                        result={"tools": [], "resultType": "complete", "ttlMs": -1, "cacheScope": "public"},
                    )
                )
            )
            # Returns naturally: the task group needs no cancel after the session context exits.

        # One combined async-with: a separately nested `async with` line mis-traces its exit
        # arcs under branch coverage on 3.11+.
        async with (
            anyio.create_task_group() as task_group,
            ClientSession(client_read, client_write, client_info=Implementation(name="cli", version="0")) as session,
        ):
            task_group.start_soon(scripted_server)
            session.adopt(
                DiscoverResult(
                    supported_versions=[LATEST_MODERN_VERSION],
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="srv", version="0"),
                )
            )
            with pytest.raises(ValidationError) as excinfo:
                with anyio.fail_after(5):
                    await session.list_tools()

            errors = excinfo.value.errors()
            assert len(errors) == 1
            assert errors[0]["loc"] == ("ttlMs",)
            # Stable pydantic-core identifier; the message text is third-party and
            # deliberately unpinned.
            assert errors[0]["type"] == "greater_than_equal"
