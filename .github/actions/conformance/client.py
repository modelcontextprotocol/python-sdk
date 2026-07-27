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
    sep-2322-client-request-state           - Drive the MRTR auto-loop (SEP-2322)
    auth/client-credentials-jwt             - Client credentials with private_key_jwt
    auth/client-credentials-basic           - Client credentials with client_secret_basic
    auth/enterprise-managed-authorization   - SEP-990 ID-JAG (RFC 8693 + RFC 7523 jwt-bearer)
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

import httpx2
import mcp_types as types
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import AnyUrl

from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.auth.extensions.client_credentials import (
    ClientCredentialsOAuthProvider,
    PrivateKeyJWTOAuthProvider,
    SignedJWTParameters,
)
from mcp.client.auth.extensions.identity_assertion import IdentityAssertionOAuthProvider
from mcp.client.auth.utils import build_protected_resource_metadata_discovery_urls
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

        async with httpx2.AsyncClient() as client:
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


@register("http-custom-headers")
async def run_http_custom_headers(server_url: str) -> None:
    """List tools, then replay the harness's `toolCalls` so x-mcp-header args mirror into headers (SEP-2243).

    The scenario supplies the exact arguments to send (including the null/edge-case values that
    exercise omission and Base64 encoding) via the context `toolCalls`; using them verbatim is
    what drives every per-parameter check. `list_tools` first so the SDK caches each tool's
    annotations; a tool the SDK dropped (invalid annotations) is skipped. Per-call failures are
    logged and skipped rather than aborting the run.
    """
    tool_calls: list[dict[str, Any]] = []
    if os.environ.get("MCP_CONFORMANCE_CONTEXT"):
        tool_calls = get_conformance_context().get("toolCalls", [])
    async with Client(server_url, mode=client_mode()) as client:
        listed = await client.list_tools()
        surfaced = {tool.name for tool in listed.tools}
        logger.debug(f"Surfaced tools: {sorted(surfaced)}")
        for call in tool_calls:
            name = call["name"]
            if name not in surfaced:
                logger.debug(f"skipping {name!r}: not surfaced by list_tools")
                continue
            try:
                await client.call_tool(name, call.get("arguments") or {})
            except Exception:
                logger.exception(f"call_tool({name!r}) failed")


@register("elicitation-sep1034-client-defaults")
async def run_elicitation_defaults(server_url: str) -> None:
    """Connect with elicitation callback that applies schema defaults."""
    async with Client(server_url, mode=client_mode(), elicitation_callback=default_elicitation_callback) as client:
        await client.list_tools()
        result = await client.call_tool("test_client_elicitation_defaults", {})
        logger.debug(f"test_client_elicitation_defaults result: {result}")


@register("sep-2322-client-request-state")
async def run_mrtr_client(server_url: str) -> None:
    """Drive the SEP-2322 client mock through `Client.call_tool`'s auto-loop.

    The mock inspects raw `tools/call` params, so registering an
    `elicitation_callback` and letting the driver run is enough to satisfy
    all five wire-shape checks: the driver echoes `request_state` byte-exact
    and omits it when the server sent none, every retry mints a fresh
    JSON-RPC id, the unrelated call between auto-loops carries no MRTR
    params, and the no-`resultType` response parses as a terminal
    `CallToolResult` so the driver never retries it.
    """

    async def confirm(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        return types.ElicitResult(action="accept", content={"confirmed": True})

    async with Client(server_url, mode=client_mode(), elicitation_callback=confirm) as client:
        await client.list_tools()

        await client.call_tool("test_mrtr_echo_state", {})
        await client.call_tool("test_mrtr_unrelated", {})
        await client.call_tool("test_mrtr_no_state", {})

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


@register("auth/enterprise-managed-authorization")
async def run_enterprise_managed_authorization(server_url: str) -> None:
    """SEP-990 enterprise-managed authorization: RFC 8693 token-exchange at the
    enterprise IdP for an ID-JAG, then RFC 7523 jwt-bearer at the MCP
    authorization server."""
    context = get_conformance_context()
    client_id = context.get("client_id")
    client_secret = context.get("client_secret")
    idp_client_id = context.get("idp_client_id")
    idp_id_token = context.get("idp_id_token")
    idp_token_endpoint = context.get("idp_token_endpoint")

    if not client_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_id'")
    if not client_secret:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'client_secret'")
    if not idp_client_id:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_client_id'")
    if not idp_id_token:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_id_token'")
    if not idp_token_endpoint:
        raise RuntimeError("MCP_CONFORMANCE_CONTEXT missing 'idp_token_endpoint'")

    # IdentityAssertionOAuthProvider takes the AS issuer as configuration (the
    # SEP-990 trust model: the resource server is never asked which AS to use).
    # The harness does not put the issuer in context, so for conformance we
    # learn it from the harness's PRM document (RFC 9728); production
    # deployments would supply it as static configuration instead.
    prm_url = build_protected_resource_metadata_discovery_urls(None, server_url)[0]
    async with httpx2.AsyncClient(timeout=30.0) as http:
        prm = (await http.get(prm_url)).raise_for_status().json()
    as_issuer = prm["authorization_servers"][0]

    async def fetch_id_jag(audience: str, resource: str) -> str:
        """Leg 1 - RFC 8693 token-exchange at the enterprise IdP."""
        async with httpx2.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                idp_token_endpoint,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "requested_token_type": "urn:ietf:params:oauth:token-type:id-jag",
                    "subject_token": idp_id_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                    "audience": audience,
                    "resource": resource,
                    "client_id": idp_client_id,
                },
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    oauth_auth = IdentityAssertionOAuthProvider(
        server_url=server_url,
        storage=InMemoryTokenStorage(),
        client_id=client_id,
        client_secret=client_secret,
        issuer=as_issuer,
        assertion_provider=fetch_id_jag,
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


async def _run_auth_session(server_url: str, oauth_auth: httpx2.Auth) -> None:
    """Common session logic for all OAuth flows."""
    http_client = httpx2.AsyncClient(auth=oauth_auth, timeout=30.0)
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
