"""SEP-2549 caching hints: producer-side stamping and client-facing TTL/scope semantics.

One test pins 2026 wire frames (typed models hide absent-vs-default keys); one scripts a
non-conformant server (the typed Server cannot author the malformed value); response caching is deferred.
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

# Non-default values (the defaults are 0/"private") prove the authored hints travelled.
PROMPTS_TTL_MS = 60_000
TEMPLATES_TTL_MS = 120_000

_NAME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


@requirement("caching:hints:prompts-list")
async def test_prompts_list_result_carries_the_handler_authored_ttl_and_scope_hints(connect: Connect) -> None:
    """Handler-authored ttlMs/cacheScope on a prompts/list result reach the client unmodified. Spec-mandated."""

    async def list_prompts(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListPromptsResult:
        assert params is not None
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
    """Handler-authored hints on a resources/templates/list result reach the client unmodified. Spec-mandated."""

    async def list_resource_templates(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        assert params is not None
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
    """Mismatched per-page cacheScopes in one cursor walk reach the client unmodified (pinned Divergence).

    When enforcement lands: re-pin to `page2.cache_scope == page1.cache_scope` and delete the Divergence.
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
    assert seen_cursors == [None, "page-2"]


@requirement("caching:ttl:absent-defaults-zero")
async def test_a_result_without_ttl_from_a_2025_server_surfaces_the_immediately_stale_defaults(
    connect: Connect,
) -> None:
    """A hint-less 2025-era result surfaces ttl_ms 0 (immediately stale) and cache_scope private.

    The ttl half is the spec SHOULD for older servers; the private half is SDK-defined behaviour.
    """

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        # Neither hint authored: the spec's "older server versions" scenario.
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        result = await client.list_tools()

    assert result.ttl_ms == 0
    assert result.cache_scope == "private"
    assert [tool.name for tool in result.tools] == ["t"]


@requirement("caching:ttl:zero-immediately-stale")
async def test_ttl_zero_results_are_refetched_on_every_access(connect: Connect) -> None:
    """Two consecutive list_tools calls against a ttlMs-0 server both reach the handler.

    Passes by construction (the client has no response cache); the pin is the regression bar for
    a future cache that wrongly serves a ttlMs-0 entry.
    """
    fetches: list[int] = []

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        assert params is not None
        fetches.append(1)
        # Explicit ttl_ms=0: the value under test, not the default's accident.
        return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})], ttl_ms=0, cache_scope="public")

    server = Server("cached", on_list_tools=list_tools)

    async with connect(server) as client:
        first = await client.list_tools()
        second = await client.list_tools()

    assert len(fetches) == 2
    assert first.ttl_ms == 0
    assert second.ttl_ms == 0


# --- wire-level: the modern HTTP entry is the only 2026 framing seam ---


@requirement("caching:input-required:no-hints")
@requirement("mrtr:input-required-result:result-type-serialized")
async def test_the_interim_input_required_frame_carries_no_caching_hints_while_the_complete_frame_does() -> None:
    """The serialized interim input_required frame carries no caching hints; the terminal complete frame does.

    Asserted at the transport seam because typed models hide absent-vs-default; the key-set pin
    also proves resultType is serialized explicitly (the stacked mrtr entry). Spec-mandated.
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
        # Non-default hints: the contrast frame is provably handler-driven, not default fill.
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
        # Combined async-with (recorder via :=): a nested `async with` mis-traces exit arcs under 3.11+ branch coverage.
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer_who,
            ) as client,
        ):
            result = await client.read_resource("res://profile")

    # resources/read generates no implicit sibling traffic, so the whole request log is asserted.
    reads = [message.message for message in recording.sent if isinstance(message.message, JSONRPCRequest)]
    assert [read.method for read in reads] == ["resources/read", "resources/read"]
    responses = {
        message.message.id: message.message.result
        for message in recording.received
        if isinstance(message, SessionMessage) and isinstance(message.message, JSONRPCResponse)
    }
    interim = responses[reads[0].id]
    complete = responses[reads[1].id]
    # Exact key vocabulary, stronger than `not in` checks: any field added to interim frames fails loudly.
    assert sorted(interim) == ["inputRequests", "resultType"]
    assert interim["resultType"] == "input_required"
    assert complete["ttlMs"] == 60_000
    assert complete["cacheScope"] == "public"
    assert complete["resultType"] == "complete"
    assert result.contents == [TextResourceContents(uri="res://profile", text="hi ada")]
    assert result.ttl_ms == 60_000


# --- scripted peer: a malformed inbound value the typed Server cannot author ---


@requirement("caching:ttl:negative-treated-as-zero")
async def test_a_negative_ttl_from_a_nonconformant_server_is_rejected_not_coerced_to_zero() -> None:
    """An inbound ttlMs of -1 raises ValidationError instead of being treated as 0 (pinned Divergence).

    When coerce-to-zero leniency lands: re-pin to ttl_ms == 0 and delete the Divergence.
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

        # Combined async-with: a nested `async with` mis-traces exit arcs under 3.11+ branch coverage.
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
            # Stable pydantic-core identifier; the message text is third-party and deliberately unpinned.
            assert errors[0]["type"] == "greater_than_equal"
