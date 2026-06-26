"""MCP unified conformance test client.

This client is designed to work with the @modelcontextprotocol/conformance npm package.
It handles all conformance test scenarios via environment variables and CLI arguments.

Contract:
    - MCP_CONFORMANCE_SCENARIO env var -> scenario name
    - MCP_CONFORMANCE_CONTEXT env var -> optional JSON (for client-credentials scenarios)
    - MCP_CONFORMANCE_PROTOCOL_VERSION env var -> spec version the harness mock
      server is speaking (e.g. "2025-11-25", "2026-07-28"). Always set; when
      --spec-version is omitted the harness picks per-scenario (LATEST_SPEC_VERSION
      for active scenarios, DRAFT_PROTOCOL_VERSION for draft-only ones).
    - Server URL as last CLI argument (sys.argv[1])
    - Must exit 0 within 30 seconds

Scenarios:
    initialize                              - Connect, initialize, list tools, close
    tools_call                              - Connect, call add_numbers(a=5, b=3), close
    sse-retry                               - Connect, call test_reconnection, close
    json-schema-ref-no-deref                - Connect, list tools (no $ref deref)
    request-metadata                        - Connect with all callbacks; client stamps _meta
    http-standard-headers                   - Connect, call a tool (Mcp-* headers checked)
    http-invalid-tool-headers               - List tools, call every surfaced tool (x-mcp-header filter)
    elicitation-sep1034-client-defaults     - Elicitation with default accept callback
    sep-2322-client-request-state           - Drive the manual MRTR retry surface
    auth/client-credentials-jwt             - Client credentials with private_key_jwt
    auth/client-credentials-basic           - Client credentials with client_secret_basic
    auth/*                                  - Authorization code flow (default for auth scenarios)
"""

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable, Coroutine
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import mcp_types as types
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import AnyUrl

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    PrivateKeyJWTOAuthProvider,
    SignedJWTParameters,
)
from mcp.client.client import Client
from mcp.client.context import ClientRequestContext
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import AuthorizationCodeResult, OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

# Set up logging to stderr (stdout is for conformance test output)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

#: Spec version the harness is running this scenario at (e.g. "2025-11-25",
#: "2026-07-28"). The harness always sets this (when --spec-version is omitted
#: it picks per-scenario: LATEST_SPEC_VERSION for active scenarios,
#: DRAFT_PROTOCOL_VERSION for draft-only ones), so None means we were invoked
#: outside the harness.
PROTOCOL_VERSION: str | None = os.environ.get("MCP_CONFORMANCE_PROTOCOL_VERSION")


def client_mode() -> str:
    """Pick the Client(mode=) for the harness leg.

    On a modern leg (2026-07-28+) -> 'auto' so Client.discover() runs and the
    _meta envelope + MCP-Protocol-Version header are stamped on every request.
    On a handshake-era leg -> 'legacy' so the initialize handshake runs exactly
    as before (no server/discover probe is sent against a mock that would 400 it).
    Outside the harness -> 'auto' (probe + fallback).
    """
    if PROTOCOL_VERSION is None or PROTOCOL_VERSION in MODERN_PROTOCOL_VERSIONS:
        return "auto"
    return "legacy"


# Type for async scenario handler functions
ScenarioHandler = Callable[[str], Coroutine[Any, None, None]]

# Registry of scenario handlers
HANDLERS: dict[str, ScenarioHandler] = {}


def register(name: str) -> Callable[[ScenarioHandler], ScenarioHandler]:
    """Register a scenario handler."""

    def decorator(fn: ScenarioHandler) -> ScenarioHandler:
        HANDLERS[name] = fn
        return fn

    return decorator


def get_conformance_context() -> dict[str, Any]:
    """Load conformance test context from MCP_CONFORMANCE_CONTEXT environment variable."""
    context_json = os.environ.get("MCP_CONFORMANCE_CONTEXT")
    if not context_json:
        raise RuntimeError(
            "MCP_CONFORMANCE_CONTEXT environment variable not set. "
            "Expected JSON with client_id, client_secret, and/or private_key_pem."
        )
    try:
        return json.loads(context_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse MCP_CONFORMANCE_CONTEXT as JSON: {e}") from e


class InMemoryTokenStorage(TokenStorage):
    """Simple in-memory token storage for conformance testing."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


class ConformanceOAuthCallbackHandler:
    """OAuth callback handler that automatically fetches the authorization URL
    and extracts the auth code, without requiring user interaction.
    """

    def __init__(self) -> None:
        self._auth_code: str | None = None
        self._state: str | None = None
        self._iss: str | None = None

    async def handle_redirect(self, authorization_url: str) -> None:
        """Fetch the authorization URL and extract the auth code from the redirect."""
        logger.debug(f"Fetching authorization URL: {authorization_url}")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                authorization_url,
                follow_redirects=False,
            )

            if response.status_code in (301, 302, 303, 307, 308):
                location = cast(str, response.headers.get("location"))
                if location:
                    redirect_url = urlparse(location)
                    query_params: dict[str, list[str]] = parse_qs(redirect_url.query)

                    if "code" in query_params:
                        self._auth_code = query_params["code"][0]
                        state_values = query_params.get("state")
                        self._state = state_values[0] if state_values else None
                        iss_values = query_params.get("iss")
                        self._iss = iss_values[0] if iss_values else None
                        logger.debug(f"Got auth code from redirect: {self._auth_code[:10]}...")
                        return
                    else:
                        raise RuntimeError(f"No auth code in redirect URL: {location}")
                else:
                    raise RuntimeError(f"No redirect location received from {authorization_url}")
            else:
                raise RuntimeError(f"Expected redirect response, got {response.status_code} from {authorization_url}")

    async def handle_callback(self) -> AuthorizationCodeResult:
        """Return the captured auth code, state, and iss."""
        if self._auth_code is None:
            raise RuntimeError("No authorization code available - was handle_redirect called?")
        result = AuthorizationCodeResult(code=self._auth_code, state=self._state, iss=self._iss)
        self._auth_code = None
        self._state = None
        self._iss = None
        return result


# --- Stub callbacks (declare capabilities in _meta without doing real work) ---


async def stub_sampling_callback(
    context: ClientRequestContext,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult | types.ErrorData:
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text=""),
        model="conformance-stub",
    )


async def stub_list_roots_callback(context: ClientRequestContext) -> types.ListRootsResult | types.ErrorData:
    return types.ListRootsResult(roots=[])


async def default_elicitation_callback(
    context: ClientRequestContext,
    params: types.ElicitRequestParams,
) -> types.ElicitResult | types.ErrorData:
    """Accept elicitation and apply defaults from the schema (SEP-1034)."""
    content: dict[str, str | int | float | bool | list[str] | None] = {}

    # For form mode, extract defaults from the requested_schema
    if isinstance(params, types.ElicitRequestFormParams):
        schema = params.requested_schema
        logger.debug(f"Elicitation schema: {schema}")
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if "default" in prop_schema:
                content[prop_name] = prop_schema["default"]
        logger.debug(f"Applied defaults: {content}")

    return types.ElicitResult(action="accept", content=content)


# --- Scenario Handlers ---


@register("initialize")
async def run_initialize(server_url: str) -> None:
    """Connect, initialize, list tools, close."""
    async with Client(server_url, mode=client_mode()) as client:
        logger.debug("Initialized successfully")
        await client.list_tools()
        logger.debug("Listed tools successfully")


@register("json-schema-ref-no-deref")
async def run_json_schema_ref_no_deref(server_url: str) -> None:
    """Initialize and list tools; the scenario fails only if the client fetches a network $ref.

    The client never walks inputSchema or resolves $refs, so listing is enough (SEP-2106).
    Pinned to mode='legacy': the harness reports PROTOCOL_VERSION=2026-07-28 for this
    scenario but its mock server only speaks the handshake-era lifecycle and 400s a
    modern-stamped tools/list. The check is lifecycle-agnostic so this is harmless.
    """
    async with Client(server_url, mode="legacy") as client:
        await client.list_tools()


@register("tools_call")
async def run_tools_call(server_url: str) -> None:
    """Connect, list tools, call add_numbers(a=5, b=3), close."""
    async with Client(server_url, mode=client_mode()) as client:
        await client.list_tools()
        result = await client.call_tool("add_numbers", {"a": 5, "b": 3})
        logger.debug(f"add_numbers result: {result}")


@register("sse-retry")
async def run_sse_retry(server_url: str) -> None:
    """Connect, list tools, call test_reconnection, close."""
    async with Client(server_url, mode=client_mode()) as client:
        await client.list_tools()
        result = await client.call_tool("test_reconnection", {})
        logger.debug(f"test_reconnection result: {result}")


@register("request-metadata")
async def run_request_metadata(server_url: str) -> None:
    """Connect on the modern path with every client capability declared.

    The scenario inspects every request's `_meta` envelope (SEP-2575) for
    protocolVersion / clientInfo / clientCapabilities, and the matching
    MCP-Protocol-Version header. mode='auto' makes the SDK send
    server/discover (covering the unsupported-version retry check), then adopt
    and stamp the envelope on the follow-up requests.
    """
    async with Client(
        server_url,
        mode=client_mode(),
        sampling_callback=stub_sampling_callback,
        list_roots_callback=stub_list_roots_callback,
        elicitation_callback=default_elicitation_callback,
    ) as client:
        await client.list_tools()
        result = await client.call_tool("add_numbers", {"a": 5, "b": 3})
        logger.debug(f"add_numbers result: {result}")


@register("http-standard-headers")
async def run_http_standard_headers(server_url: str) -> None:
    """Connect on the modern path so Mcp-Method / Mcp-Name / MCP-Protocol-Version are sent (SEP-2243)."""
    async with Client(server_url, mode=client_mode()) as client:
        await client.list_tools()
        result = await client.call_tool("add_numbers", {"a": 5, "b": 3})
        logger.debug(f"add_numbers result: {result}")


def _stub_required_args(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Minimal arguments satisfying a tool inputSchema's required list."""
    by_type: dict[str, Any] = {
        "string": "x",
        "integer": 0,
        "number": 0,
        "boolean": False,
        "object": {},
        "array": [],
        "null": None,
    }
    properties = input_schema.get("properties", {})
    return {name: by_type.get(properties.get(name, {}).get("type"), "x") for name in input_schema.get("required", [])}


@register("http-invalid-tool-headers")
async def run_http_invalid_tool_headers(server_url: str) -> None:
    """List tools, then call every tool the SDK surfaces (SEP-2243).

    The harness mock advertises one valid tool plus several with malformed
    x-mcp-header annotations (empty, non-primitive type, duplicate, invalid
    chars). The scenario passes if valid_tool is called and the malformed
    ones are not -- so a conforming client filters them out of the list_tools
    result and the loop below never sees them. The scenario sets
    allowClientError, so a per-call failure is logged and skipped rather
    than aborting the whole run.
    """
    async with Client(server_url, mode=client_mode()) as client:
        listed = await client.list_tools()
        logger.debug(f"Surfaced tools: {[t.name for t in listed.tools]}")
        for tool in listed.tools:
            try:
                await client.call_tool(tool.name, _stub_required_args(tool.input_schema))
            except Exception:
                logger.exception(f"call_tool({tool.name!r}) failed")


def _stub_args_for_custom_headers(input_schema: dict[str, Any]) -> dict[str, Any]:
    """Arguments exercising every `x-mcp-header`-annotated property in a tool schema.

    Each annotated property gets a type-appropriate value so the SDK mirrors it into an
    `Mcp-Param-*` header; required properties without an annotation get a placeholder so
    the call is well-formed.
    """
    by_type: dict[str, Any] = {"string": "us-west1", "integer": 42, "boolean": False, "number": 3.14}
    properties: dict[str, Any] = input_schema.get("properties", {})
    arguments: dict[str, Any] = {}
    for name, schema in properties.items():
        if "x-mcp-header" in schema:
            arguments[name] = by_type.get(schema.get("type"), "x")
    for name in input_schema.get("required", []):
        arguments.setdefault(name, by_type.get(properties.get(name, {}).get("type"), "x"))
    return arguments


@register("http-custom-headers")
async def run_http_custom_headers(server_url: str) -> None:
    """List tools, then call each surfaced tool so its `x-mcp-header` args mirror into headers (SEP-2243).

    A conforming client drops tools with invalid annotations during `list_tools` (e.g. the
    harness's `number`-typed properties, which the spec forbids), so the loop only calls tools
    whose annotations are valid; for those, the SDK emits the `Mcp-Param-*` headers the scenario
    checks. Per-call failures are logged and skipped rather than aborting the run.
    """
    async with Client(server_url, mode=client_mode()) as client:
        listed = await client.list_tools()
        logger.debug(f"Surfaced tools: {[t.name for t in listed.tools]}")
        for tool in listed.tools:
            try:
                await client.call_tool(tool.name, _stub_args_for_custom_headers(tool.input_schema))
            except Exception:
                logger.exception(f"call_tool({tool.name!r}) failed")


@register("elicitation-sep1034-client-defaults")
async def run_elicitation_defaults(server_url: str) -> None:
    """Connect with elicitation callback that applies schema defaults."""
    async with Client(server_url, mode=client_mode(), elicitation_callback=default_elicitation_callback) as client:
        await client.list_tools()
        result = await client.call_tool("test_client_elicitation_defaults", {})
        logger.debug(f"test_client_elicitation_defaults result: {result}")


@register("sep-2322-client-request-state")
async def run_mrtr_client(server_url: str) -> None:
    """Drive the manual MRTR retry surface against the SEP-2322 client mock.

    The mock speaks the modern lifecycle (server/discover, no initialize) and
    inspects the wire params of each tools/call round, so this exercises the
    explicit allow_input_required=True path rather than an auto-loop: round 1
    receives an InputRequiredResult, the fixture fulfils the elicitation
    locally, then round 2 retries with input_responses + the echoed
    request_state. Passing request_state straight off the typed result -- a
    str when the server sent one, None when it didn't -- lets the
    serializer's exclude_none drop the key in the no-state case without a
    branch here. The unrelated call between rounds proves MRTR params don't
    leak across tools, and the no-result-type call must parse as a complete
    CallToolResult with no retry.
    """
    async with Client(server_url, mode=client_mode()) as client:
        await client.list_tools()
        confirm = {"confirm": types.ElicitResult(action="accept", content={"confirmed": True})}

        r1 = await client.call_tool("test_mrtr_echo_state", {}, allow_input_required=True)
        assert isinstance(r1, types.InputRequiredResult)

        await client.call_tool("test_mrtr_unrelated", {})

        await client.call_tool(
            "test_mrtr_echo_state",
            {},
            input_responses=confirm,
            request_state=r1.request_state,
            allow_input_required=True,
        )

        r2 = await client.call_tool("test_mrtr_no_state", {}, allow_input_required=True)
        assert isinstance(r2, types.InputRequiredResult)
        await client.call_tool(
            "test_mrtr_no_state",
            {},
            input_responses=confirm,
            request_state=r2.request_state,
            allow_input_required=True,
        )

        result = await client.call_tool("test_mrtr_no_result_type", {})
        assert isinstance(result, types.CallToolResult)


@register("auth/client-credentials-jwt")
async def run_client_credentials_jwt(server_url: str) -> None:
    """Client credentials flow with private_key_jwt authentication."""
    context = get_conformance_context()
    client_id = context.get("client_id")
    private_key_pem = context.get("private_key_pem")
    signing_algorithm = context.get("signing_algorithm", "ES256")

    if not client_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_id'")
    if not private_key_pem:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'private_key_pem'")

    jwt_params = SignedJWTParameters(
        issuer=client_id,
        subject=client_id,
        signing_algorithm=signing_algorithm,
        signing_key=private_key_pem,
    )

    oauth_auth = PrivateKeyJWTOAuthProvider(
        server_url=server_url,
        storage=InMemoryTokenStorage(),
        client_id=client_id,
        assertion_provider=jwt_params.create_assertion_provider(),
    )

    await _run_auth_session(server_url, oauth_auth)


@register("auth/client-credentials-basic")
async def run_client_credentials_basic(server_url: str) -> None:
    """Client credentials flow with client_secret_basic authentication."""
    context = get_conformance_context()
    client_id = context.get("client_id")
    client_secret = context.get("client_secret")

    if not client_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_id'")
    if not client_secret:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_secret'")

    oauth_auth = ClientCredentialsOAuthProvider(
        server_url=server_url,
        storage=InMemoryTokenStorage(),
        client_id=client_id,
        client_secret=client_secret,
        token_endpoint_auth_method="client_secret_basic",
    )

    await _run_auth_session(server_url, oauth_auth)


async def run_auth_code_client(server_url: str) -> None:
    """Authorization code flow (default for auth/* scenarios)."""
    callback_handler = ConformanceOAuthCallbackHandler()
    storage = InMemoryTokenStorage()

    # Check for pre-registered client credentials from context
    context_json = os.environ.get("MCP_CONFORMANCE_CONTEXT")
    if context_json:
        try:
            context = json.loads(context_json)
            client_id = context.get("client_id")
            client_secret = context.get("client_secret")
            if client_id:
                await storage.set_client_info(
                    OAuthClientInformationFull(
                        client_id=client_id,
                        client_secret=client_secret,
                        redirect_uris=[AnyUrl("http://localhost:3000/callback")],
                        token_endpoint_auth_method="client_secret_basic" if client_secret else "none",
                    )
                )
                logger.debug(f"Pre-loaded client credentials: client_id={client_id}")
        except json.JSONDecodeError:
            logger.exception("Failed to parse MCP_CONFORMANCE_CONTEXT")

    oauth_auth = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="conformance-client",
            redirect_uris=[AnyUrl("http://localhost:3000/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
        redirect_handler=callback_handler.handle_redirect,
        callback_handler=callback_handler.handle_callback,
        client_metadata_url="https://conformance-test.local/client-metadata.json",
    )

    await _run_auth_session(server_url, oauth_auth)


async def _run_auth_session(server_url: str, oauth_auth: OAuthClientProvider) -> None:
    """Common session logic for all OAuth flows."""
    http_client = httpx.AsyncClient(auth=oauth_auth, timeout=30.0)
    transport = streamable_http_client(url=server_url, http_client=http_client)
    async with Client(transport, mode=client_mode(), elicitation_callback=default_elicitation_callback) as client:
        logger.debug("Initialized successfully")

        tools_result = await client.list_tools()
        logger.debug(f"Listed tools: {[t.name for t in tools_result.tools]}")

        # Call the first available tool (different tests have different tools)
        if tools_result.tools:
            tool_name = tools_result.tools[0].name
            try:
                result = await client.call_tool(tool_name, {})
                logger.debug(f"Called {tool_name}, result: {result}")
            except Exception as e:
                logger.debug(f"Tool call result/error: {e}")

    logger.debug("Connection closed successfully")


def main() -> None:
    """Main entry point for the conformance client."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <server-url>", file=sys.stderr)
        sys.exit(1)

    server_url = sys.argv[1]
    scenario = os.environ.get("MCP_CONFORMANCE_SCENARIO")
    logger.debug(f"Conformance protocol version: {PROTOCOL_VERSION!r} -> mode={client_mode()!r}")

    if scenario:
        logger.debug(f"Running explicit scenario '{scenario}' against {server_url}")
        handler = HANDLERS.get(scenario)
        if handler:
            asyncio.run(handler(server_url))
        elif scenario.startswith("auth/"):
            asyncio.run(run_auth_code_client(server_url))
        else:
            print(f"Unknown scenario: {scenario}", file=sys.stderr)
            sys.exit(1)
    else:
        logger.debug(f"Running default auth flow against {server_url}")
        asyncio.run(run_auth_code_client(server_url))


if __name__ == "__main__":
    main()
