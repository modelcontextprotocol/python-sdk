"""Shared OAuth 401/403 flow generators.

These generators are reused by OAuthClientProvider and MultiProtocolAuthProvider. They yield requests so the caller
can send them with a single HTTP client, avoiding deadlocks while performing OAuth discovery and authentication.
"""

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from mcp.client.auth.exceptions import OAuthFlowError
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
    create_client_info_from_metadata_url,
    create_client_registration_request,
    create_oauth_metadata_request,
    extract_field_from_www_auth,
    extract_resource_metadata_from_www_auth,
    extract_scope_from_www_auth,
    get_client_metadata_scopes,
    handle_auth_metadata_response,
    handle_protected_resource_response,
    handle_registration_response,
    should_use_client_metadata_url,
)

if TYPE_CHECKING:
    from mcp.shared.auth import ProtectedResourceMetadata


class _OAuth401FlowProvider(Protocol):
    """Provider interface for oauth_401_flow_generator (OAuthClientProvider duck type)."""

    @property
    def context(self) -> Any: ...  # pragma: lax no cover

    async def _validate_resource_match(self, prm: "ProtectedResourceMetadata") -> None: ...  # pragma: lax no cover

    async def _perform_authorization(self) -> httpx.Request: ...  # pragma: lax no cover

    async def _handle_token_response(self, response: httpx.Response) -> None: ...  # pragma: lax no cover


logger = logging.getLogger(__name__)


async def oauth_401_flow_generator(
    provider: _OAuth401FlowProvider,
    request: httpx.Request,
    response_401: httpx.Response,
    *,
    initial_prm: "ProtectedResourceMetadata | None" = None,
) -> AsyncGenerator[httpx.Request, httpx.Response]:
    """OAuth 401 flow: PRM discovery (optional) → AS metadata discovery → scope → registration/CIMD → auth → token.

    The generator yields requests, and the caller is responsible for sending them and feeding responses back into the
    generator. This enables a single-client, yield-based OAuth flow usable by both OAuthClientProvider and
    MultiProtocolAuthProvider.

    Args:
        provider: Provider instance (OAuthClientProvider duck type). Must provide ``context``,
            ``_perform_authorization()``, and ``_handle_token_response()``.
        request: The original request that triggered 401.
        response_401: The 401 response.
        initial_prm: If provided, PRM discovery is skipped (MultiProtocolAuthProvider may pre-discover it).
    """
    ctx = provider.context

    if initial_prm is not None:
        await provider._validate_resource_match(initial_prm)  # type: ignore[reportPrivateUsage]
        ctx.protected_resource_metadata = initial_prm
        if initial_prm.authorization_servers:
            ctx.auth_server_url = str(initial_prm.authorization_servers[0])
    else:
        # Step 1: Discover protected resource metadata (SEP-985 with fallback support)
        www_auth_resource_metadata_url = extract_resource_metadata_from_www_auth(response_401)
        prm_discovery_urls = build_protected_resource_metadata_discovery_urls(
            www_auth_resource_metadata_url, ctx.server_url
        )

        for url in prm_discovery_urls:
            discovery_request = create_oauth_metadata_request(url)
            discovery_response = yield discovery_request

            prm = await handle_protected_resource_response(discovery_response)
            if prm:
                await provider._validate_resource_match(prm)  # type: ignore[reportPrivateUsage]
                ctx.protected_resource_metadata = prm
                assert len(prm.authorization_servers) > 0
                ctx.auth_server_url = str(prm.authorization_servers[0])
                break
            logger.debug("Protected resource metadata discovery failed: %s", url)

    # Step 2: Discover OAuth Authorization Server Metadata (OASM)
    asm_discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(ctx.auth_server_url, ctx.server_url)

    for url in asm_discovery_urls:
        oauth_metadata_request = create_oauth_metadata_request(url)
        oauth_metadata_response = yield oauth_metadata_request

        ok, asm = await handle_auth_metadata_response(oauth_metadata_response)
        if not ok:
            break
        if asm:
            ctx.oauth_metadata = asm
            break
        logger.debug("OAuth metadata discovery failed: %s", url)

    # Step 3: Apply scope selection strategy
    ctx.client_metadata.scope = get_client_metadata_scopes(
        extract_scope_from_www_auth(response_401),
        ctx.protected_resource_metadata,
        ctx.oauth_metadata,
    )

    # Step 4: Register client or use URL-based client ID (CIMD)
    # For client_credentials, a fixed client_id/client_secret must be provided; do not attempt DCR/CIMD.
    if "client_credentials" in (ctx.client_metadata.grant_types or []) and not ctx.client_info:
        raise OAuthFlowError("Missing client_info for client_credentials flow")

    if not ctx.client_info:
        if should_use_client_metadata_url(ctx.oauth_metadata, ctx.client_metadata_url):
            logger.debug("Using URL-based client ID (CIMD): %s", ctx.client_metadata_url)
            client_information = create_client_info_from_metadata_url(
                ctx.client_metadata_url,  # type: ignore[arg-type]
                redirect_uris=ctx.client_metadata.redirect_uris,
            )
            ctx.client_info = client_information
            await ctx.storage.set_client_info(client_information)
        else:
            registration_request = create_client_registration_request(
                ctx.oauth_metadata,
                ctx.client_metadata,
                ctx.get_authorization_base_url(ctx.server_url),
            )
            registration_response = yield registration_request
            client_information = await handle_registration_response(registration_response)
            ctx.client_info = client_information
            await ctx.storage.set_client_info(client_information)

    # Step 5: Perform authorization and complete token exchange
    token_request = await provider._perform_authorization()  # type: ignore[reportPrivateUsage]
    token_response = yield token_request
    await provider._handle_token_response(token_response)  # type: ignore[reportPrivateUsage]


async def oauth_403_flow_generator(
    provider: _OAuth401FlowProvider,
    request: httpx.Request,
    response_403: httpx.Response,
) -> AsyncGenerator[httpx.Request, httpx.Response]:
    """OAuth 403 insufficient_scope flow: update scope → re-authorize → token exchange."""
    ctx = provider.context
    error = extract_field_from_www_auth(response_403, "error")

    if error == "insufficient_scope":
        ctx.client_metadata.scope = get_client_metadata_scopes(
            extract_scope_from_www_auth(response_403), ctx.protected_resource_metadata
        )
        token_request = await provider._perform_authorization()  # type: ignore[reportPrivateUsage]
        token_response = yield token_request
        await provider._handle_token_response(token_response)  # type: ignore[reportPrivateUsage]
