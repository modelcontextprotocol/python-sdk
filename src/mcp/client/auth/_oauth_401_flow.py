"""
共享的 OAuth 401/403 流程 generator。

供 OAuthClientProvider 与 MultiProtocolAuthProvider 复用，通过 yield 发送请求，
实现单 client、无死锁的 OAuth 发现与认证流程。
"""

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any, Protocol

import httpx

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
    def context(self) -> Any:
        ...

    async def _perform_authorization(self) -> httpx.Request:
        ...

    async def _handle_token_response(self, response: httpx.Response) -> None:
        ...


logger = logging.getLogger(__name__)


async def oauth_401_flow_generator(
    provider: _OAuth401FlowProvider,
    request: httpx.Request,
    response_401: httpx.Response,
    *,
    initial_prm: "ProtectedResourceMetadata | None" = None,
) -> AsyncGenerator[httpx.Request, httpx.Response]:
    """
    OAuth 401 流程：PRM 发现（可跳过）→ AS 发现 → scope → 注册/CIMD → 授权码 → Token 交换。

    通过 yield 发出请求，由调用方负责发送并传回响应。供 OAuthClientProvider 与
    MultiProtocolAuthProvider 复用，实现单 client、yield 模式的 OAuth 流程。

    Args:
        provider: OAuthClientProvider 实例，需有 context、_perform_authorization、_handle_token_response
        request: 触发 401 的原始请求
        response_401: 401 响应
        initial_prm: 若提供则跳过 PRM 发现（MultiProtocolAuthProvider 已事先完成）
    """
    ctx = provider.context

    if initial_prm is not None:
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
                ctx.protected_resource_metadata = prm
                assert len(prm.authorization_servers) > 0
                ctx.auth_server_url = str(prm.authorization_servers[0])
                break
            logger.debug("Protected resource metadata discovery failed: %s", url)

    # Step 2: Discover OAuth Authorization Server Metadata (OASM)
    asm_discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
        ctx.auth_server_url, ctx.server_url
    )

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
    """
    OAuth 403 insufficient_scope 流程：更新 scope → 重新授权 → Token 交换。
    """
    ctx = provider.context
    error = extract_field_from_www_auth(response_403, "error")

    if error == "insufficient_scope":
        ctx.client_metadata.scope = get_client_metadata_scopes(
            extract_scope_from_www_auth(response_403), ctx.protected_resource_metadata
        )
        token_request = await provider._perform_authorization()  # type: ignore[reportPrivateUsage]
        token_response = yield token_request
        await provider._handle_token_response(token_response)  # type: ignore[reportPrivateUsage]
