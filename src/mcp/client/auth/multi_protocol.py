"""Multi-protocol authentication provider.

This module provides a unified HTTP authentication flow based on protocol discovery and an injected protocol registry.
It supports OAuth 2.0, API keys, and other pluggable auth protocols.

Token storage: dual contract and conversion rules
-------------------------------------------------
- **oauth2 contract** (used by :class:`~mcp.client.auth.oauth2.OAuthClientProvider`):
  ``get_tokens() -> OAuthToken | None`` and ``set_tokens(OAuthToken)``; optionally
  ``get_client_info()/set_client_info()``.
- **multi_protocol contract** (``TokenStorage`` in this module):
  ``get_tokens() -> AuthCredentials | OAuthToken | None`` and ``set_tokens(AuthCredentials | OAuthToken)``.
- **conversion rule**: conversions happen in the provider, without expanding protocol APIs:
  - Read path: ``_get_credentials()`` calls ``storage.get_tokens()``. If it returns an ``OAuthToken``, it is
    converted to :class:`~mcp.shared.auth.OAuthCredentials` via ``_oauth_token_to_credentials``.
  - Write path: credentials produced by discovery/auth are converted via ``_credentials_to_storage`` before
    calling ``storage.set_tokens()``. Only ``OAuthCredentials`` are converted into ``OAuthToken``; other
    credential types are stored as-is.
- As a result, legacy storage implementations that only support ``get_tokens/set_tokens(OAuthToken)`` can be used
  directly with :class:`~mcp.client.auth.multi_protocol.MultiProtocolAuthProvider` without modification. Optionally,
  wrap them with :class:`~mcp.client.auth.multi_protocol.OAuthTokenStorageAdapter` to satisfy the multi-protocol
  contract explicitly.
"""

import json
import logging
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any, Protocol, cast
from urllib.parse import urljoin

import anyio
import httpx
from pydantic import ValidationError

from mcp.client.auth._oauth_401_flow import oauth_401_flow_generator
from mcp.client.auth.oauth2 import OAuthClientProvider
from mcp.client.auth.oauth2 import TokenStorage as OAuth2TokenStorage
from mcp.client.auth.protocol import AuthContext, AuthProtocol, DPoPEnabledProtocol
from mcp.client.auth.utils import (
    build_protected_resource_metadata_discovery_urls,
    create_oauth_metadata_request,
    extract_auth_protocols_from_www_auth,
    extract_default_protocol_from_www_auth,
    extract_field_from_www_auth,
    extract_protocol_preferences_from_www_auth,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    handle_protected_resource_response,
)
from mcp.client.streamable_http import MCP_PROTOCOL_VERSION
from mcp.shared.auth import (
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthCredentials,
    OAuthToken,
    ProtectedResourceMetadata,
)

logger = logging.getLogger(__name__)

# Protocol preferences: any protocol without an explicit preference should sort last.
UNSPECIFIED_PROTOCOL_PREFERENCE: int = sys.maxsize


class TokenStorage(Protocol):
    """Credential storage interface (multi-protocol contract).

    The multi-protocol contract supports:
    - ``get_tokens() -> AuthCredentials | OAuthToken | None``
    - ``set_tokens(AuthCredentials | OAuthToken)``

    Legacy storage implementations that only support ``OAuthToken`` are still usable because the provider converts
    between ``OAuthToken`` and ``OAuthCredentials`` internally. Alternatively, wrap such storage using
    :class:`~mcp.client.auth.multi_protocol.OAuthTokenStorageAdapter`.
    """

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        """Return stored credentials, if any."""
        ...

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        """Store credentials."""
        ...


def _oauth_token_to_credentials(token: OAuthToken) -> OAuthCredentials:
    """Convert an OAuthToken into OAuthCredentials (for legacy storage compatibility)."""
    from mcp.shared.auth_utils import calculate_token_expiry

    expires_at: int | None = None
    if token.expires_in is not None:
        expiry = calculate_token_expiry(token.expires_in)
        expires_at = int(expiry) if expiry is not None else None
    return OAuthCredentials(
        protocol_id="oauth2",
        access_token=token.access_token,
        token_type=token.token_type,
        refresh_token=token.refresh_token,
        scope=token.scope,
        expires_at=expires_at,
    )


def _credentials_to_storage(credentials: AuthCredentials) -> AuthCredentials | OAuthToken:
    """Convert AuthCredentials to a storage-friendly shape.

    This exists to support legacy storage implementations that only accept OAuthToken:
    OAuthCredentials are converted into OAuthToken; other credential types are returned as-is.
    """
    if isinstance(credentials, OAuthCredentials):
        expires_in: int | None = None
        if credentials.expires_at is not None:
            delta = credentials.expires_at - int(time.time())
            expires_in = max(0, delta)
        return OAuthToken(
            access_token=credentials.access_token,
            token_type=credentials.token_type,
            expires_in=expires_in,
            scope=credentials.scope,
            refresh_token=credentials.refresh_token,
        )
    return credentials


class _OAuthTokenOnlyStorage(Protocol):
    """OAuthToken-only storage contract (wrapped by OAuthTokenStorageAdapter)."""

    async def get_tokens(self) -> OAuthToken | None: ...  # pragma: lax no cover

    async def set_tokens(self, tokens: OAuthToken) -> None: ...  # pragma: lax no cover


class OAuthTokenStorageAdapter:
    """Adapt an OAuthToken-only storage to the multi-protocol TokenStorage interface.

    - Read path: converts OAuthToken into OAuthCredentials.
    - Write path: converts OAuthCredentials into OAuthToken before calling the wrapped storage.
      Only OAuth credentials are persisted; non-OAuth credentials (e.g. APIKeyCredentials) are not written.
    """

    def __init__(self, wrapped: _OAuthTokenOnlyStorage) -> None:
        self._wrapped = wrapped

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        raw = await self._wrapped.get_tokens()
        if raw is None:
            return None
        return _oauth_token_to_credentials(raw)

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        to_store = _credentials_to_storage(tokens) if isinstance(tokens, AuthCredentials) else tokens
        if isinstance(to_store, OAuthToken):
            await self._wrapped.set_tokens(to_store)


class MultiProtocolAuthProvider(httpx.Auth):
    """Multi-protocol httpx authentication provider.

    Integrates with httpx to prepare authentication for requests. On 401/403, it performs discovery and
    authentication based on the server's hints and the injected protocol instances.
    """

    requires_response_body = True

    def __init__(
        self,
        server_url: str,
        storage: TokenStorage,
        protocols: list[AuthProtocol] | None = None,
        http_client: httpx.AsyncClient | None = None,
        dpop_storage: Any = None,
        dpop_enabled: bool = False,
        timeout: float = 300.0,
    ):
        self.server_url = server_url
        self.storage = storage
        self.protocols = protocols or []
        self._http_client = http_client
        self.dpop_storage = dpop_storage
        self.dpop_enabled = dpop_enabled
        self.timeout = timeout
        self._lock = anyio.Lock()
        self._initialized = False
        self._current_protocol: AuthProtocol | None = None
        self._protocols_by_id: dict[str, AuthProtocol] = {}

    def _initialize(self) -> None:
        """Build an index from protocol_id to protocol instances."""
        self._protocols_by_id = {p.protocol_id: p for p in self.protocols}
        self._initialized = True

    def _get_protocol(self, protocol_id: str) -> AuthProtocol | None:
        """Return a protocol instance by protocol_id."""
        return self._protocols_by_id.get(protocol_id)

    async def _get_credentials(self) -> AuthCredentials | None:
        """Load credentials from storage and normalize to AuthCredentials.

        If storage returns OAuthToken, convert it to OAuthCredentials for compatibility.
        """
        raw = await self.storage.get_tokens()
        if raw is None:
            return None
        if isinstance(raw, AuthCredentials):
            return raw
        # raw is OAuthToken here (TokenStorage returns AuthCredentials | OAuthToken | None)
        return _oauth_token_to_credentials(raw)

    def _is_credentials_valid(self, credentials: AuthCredentials | None) -> bool:
        """Return True if credentials are valid (e.g. not expired), according to protocol implementation."""
        if credentials is None:
            return False
        protocol = self._get_protocol(credentials.protocol_id)
        if protocol is None:
            return False
        return protocol.validate_credentials(credentials)

    async def _ensure_dpop_initialized(self, credentials: AuthCredentials) -> None:
        """Ensure DPoP is initialized for the protocol if enabled."""
        if not self.dpop_enabled:
            return
        protocol = self._get_protocol(credentials.protocol_id)
        if protocol is not None and isinstance(protocol, DPoPEnabledProtocol):
            if protocol.supports_dpop():
                await protocol.initialize_dpop()

    def _prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        """Apply protocol-specific authentication to a request, including DPoP proof if enabled."""
        protocol = self._get_protocol(credentials.protocol_id)
        if protocol is not None:
            protocol.prepare_request(request, credentials)

            # Generate and attach DPoP proof if enabled and protocol supports it
            if self.dpop_enabled and isinstance(protocol, DPoPEnabledProtocol):
                if protocol.supports_dpop():
                    generator = protocol.get_dpop_proof_generator()
                    if generator is not None:
                        # Get access token for ath claim binding
                        access_token: str | None = None
                        if isinstance(credentials, OAuthCredentials):
                            access_token = credentials.access_token
                        proof = generator.generate_proof(
                            str(request.method),
                            str(request.url),
                            credential=access_token,
                        )
                        request.headers["DPoP"] = proof

    async def _parse_protocols_from_discovery_response(
        self, response: httpx.Response, prm: ProtectedResourceMetadata | None
    ) -> list[AuthProtocolMetadata]:
        """Parse ``/.well-known/authorization_servers`` response; fall back to PRM if needed."""
        if response.status_code == 200:
            try:
                content = await response.aread()
                data = json.loads(content.decode())
                raw = data.get("protocols")
                protocols_data: list[dict[str, Any]] = cast(list[dict[str, Any]], raw) if isinstance(raw, list) else []
                if protocols_data:
                    return [AuthProtocolMetadata.model_validate(p) for p in protocols_data]
            except (ValidationError, ValueError, KeyError, TypeError) as e:
                logger.debug("Unified authorization_servers parse failed: %s", e)
        if prm is not None and prm.mcp_auth_protocols:
            return list(prm.mcp_auth_protocols)
        return []

    async def _handle_403_response(self, response: httpx.Response, request: httpx.Request) -> None:
        """Handle 403 by parsing/logging error and scope (no retries)."""
        error = extract_field_from_www_auth(response, "error")
        scope = extract_field_from_www_auth(response, "scope")
        if error or scope:
            logger.debug("403 WWW-Authenticate: error=%s scope=%s", error, scope)

    async def async_auth_flow(self, request: httpx.Request) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Entry point for the HTTPX auth flow: load/validate credentials, send request, handle 401/403."""
        async with self._lock:
            if not self._initialized:
                self._initialize()

            credentials = await self._get_credentials()
            if not credentials or not self._is_credentials_valid(credentials):
                # Without valid credentials, send the request first and rely on the 401 handler below
                # for discovery and authentication.
                pass
            else:
                await self._ensure_dpop_initialized(credentials)
                self._prepare_request(request, credentials)

        response = yield request

        if response.status_code == 401:
            original_request = request
            original_401_response = response
            async with self._lock:
                resource_metadata_url = extract_resource_metadata_from_www_auth(response)
                auth_protocols_header = extract_auth_protocols_from_www_auth(response)
                default_protocol = extract_default_protocol_from_www_auth(response)
                protocol_preferences = extract_protocol_preferences_from_www_auth(response)
                server_url = str(request.url)
                attempted_any = False
                last_auth_error: Exception | None = None

                # Step 1: PRM discovery (yield)
                prm: ProtectedResourceMetadata | None = None
                prm_urls = build_protected_resource_metadata_discovery_urls(resource_metadata_url, server_url)
                for url in prm_urls:
                    prm_req = create_oauth_metadata_request(url)
                    prm_resp = yield prm_req
                    prm = await handle_protected_resource_response(prm_resp)
                    if prm is not None:
                        break

                # Step 2: Protocol discovery (yield)
                discovery_url = urljoin(
                    server_url.rstrip("/") + "/",
                    ".well-known/authorization_servers",
                )
                discovery_req = create_oauth_metadata_request(discovery_url)
                discovery_resp = yield discovery_req
                protocols_metadata = await self._parse_protocols_from_discovery_response(discovery_resp, prm)

                available: list[str] = (
                    [m.protocol_id for m in protocols_metadata]
                    if protocols_metadata
                    else (list(auth_protocols_header) if auth_protocols_header is not None else [])
                )
                if not available and prm is not None and prm.authorization_servers:
                    # OAuth fallback: if PRM indicates OAuth ASes but unified discovery did not
                    # return protocol metadata (and the server did not hint via WWW-Authenticate),
                    # still attempt OAuth2 if injected.
                    available = ["oauth2"]
                    logger.debug("No protocols discovered; falling back to oauth2 via PRM authorization_servers")
                if not available:
                    logger.debug("No available protocols from discovery or WWW-Authenticate")
                else:
                    # Select protocol candidates based on server hints, but only
                    # attempt protocols that are actually injected as instances.
                    candidates_raw: list[str | None] = [default_protocol]
                    preferences = protocol_preferences
                    if preferences is not None:

                        def preference_key(protocol_id: str) -> int:
                            return preferences.get(protocol_id, UNSPECIFIED_PROTOCOL_PREFERENCE)

                        candidates_raw.extend(sorted(available, key=preference_key))
                    candidates_raw.extend(available)

                    # De-duplicate while preserving order.
                    candidates_str = [pid for pid in candidates_raw if pid is not None]
                    candidates = list(dict.fromkeys(candidates_str))

                    metadata_by_id = {m.protocol_id: m for m in protocols_metadata} if protocols_metadata else {}

                    for selected_id in candidates:
                        protocol = self._get_protocol(selected_id)
                        if protocol is None:
                            logger.debug("Protocol %s not injected as instance; skipping", selected_id)
                            continue
                        attempted_any = True

                        protocol_metadata = metadata_by_id.get(selected_id)

                        try:
                            if selected_id == "oauth2":
                                # OAuth: drive shared generator (single client, yield)
                                oauth_protocol = protocol
                                provider = OAuthClientProvider(
                                    server_url=server_url,
                                    client_metadata=getattr(oauth_protocol, "_client_metadata"),
                                    storage=cast(OAuth2TokenStorage, self.storage),
                                    redirect_handler=getattr(oauth_protocol, "_redirect_handler", None),
                                    callback_handler=getattr(oauth_protocol, "_callback_handler", None),
                                    timeout=getattr(oauth_protocol, "_timeout", self.timeout),
                                    client_metadata_url=getattr(oauth_protocol, "_client_metadata_url", None),
                                    fixed_client_info=getattr(oauth_protocol, "_fixed_client_info", None),
                                )
                                provider.context.protocol_version = request.headers.get(MCP_PROTOCOL_VERSION)
                                gen = oauth_401_flow_generator(
                                    provider, original_request, original_401_response, initial_prm=prm
                                )
                                auth_req = await gen.__anext__()
                                while True:
                                    auth_resp = yield auth_req
                                    try:
                                        auth_req = await gen.asend(auth_resp)
                                    except StopAsyncIteration:
                                        break
                            else:
                                # API Key, mTLS, etc.: call protocol.authenticate
                                context = AuthContext(
                                    server_url=server_url,
                                    storage=self.storage,
                                    protocol_id=selected_id,
                                    protocol_metadata=protocol_metadata,
                                    current_credentials=None,
                                    dpop_storage=self.dpop_storage,
                                    dpop_enabled=self.dpop_enabled,
                                    http_client=self._http_client,
                                    resource_metadata_url=resource_metadata_url,
                                    protected_resource_metadata=prm,
                                    scope_from_www_auth=extract_scope_from_www_auth(original_401_response),
                                )
                                credentials = await protocol.authenticate(context)
                                to_store = _credentials_to_storage(credentials)
                                await self.storage.set_tokens(to_store)

                            # Stop after first successful protocol path that stores credentials
                            break
                        except Exception as e:
                            last_auth_error = e
                            logger.debug("Protocol %s authentication failed: %s", selected_id, e)
                            continue

                credentials = await self._get_credentials()
                if credentials and self._is_credentials_valid(credentials):
                    await self._ensure_dpop_initialized(credentials)
                    self._prepare_request(request, credentials)
                    response = yield request
                else:
                    if attempted_any and last_auth_error is not None:
                        # If we did attempt an injected protocol and it failed, surface the error
                        # instead of returning a potentially confusing 401.
                        raise last_auth_error
                    # Ensure we do not leak discovery responses as the final response:
                    # retry the original request once without new credentials so the
                    # caller receives a response corresponding to the original request.
                    response = yield original_request
        elif response.status_code == 403:
            await self._handle_403_response(response, request)
