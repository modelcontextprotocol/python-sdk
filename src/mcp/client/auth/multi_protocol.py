"""
多协议认证提供者。

提供基于协议注册表与发现的统一 HTTP 认证流程，支持 OAuth 2.0、API Key 等协议。

TokenStorage 双契约与转换约定
----------------------------
- **oauth2 契约**（OAuthClientProvider 使用）：get_tokens() -> OAuthToken | None，
  set_tokens(OAuthToken)；另可有 get_client_info/set_client_info。
- **multi_protocol 契约**（本模块 TokenStorage）：get_tokens() -> AuthCredentials | OAuthToken | None，
  set_tokens(AuthCredentials | OAuthToken)。
- **转换约定**：MultiProtocolAuthProvider 在调用方做转换，不扩展协议方法：
  - 取回时：_get_credentials() 调用 storage.get_tokens()，若得到 OAuthToken 则经
    _oauth_token_to_credentials 转为 OAuthCredentials。
  - 写入时：_discover_and_authenticate 得到 AuthCredentials 后经 _credentials_to_storage
    转为 OAuthToken（仅 OAuthCredentials 转 OAuthToken，其他凭证原样），再调用
    storage.set_tokens(to_store)。
- 因此仅实现 get_tokens/set_tokens(OAuthToken) 的旧存储可直接用于 MultiProtocolAuthProvider，
  无需改存储实现。可选使用 OAuthTokenStorageAdapter 将此类存储包装为满足 multi_protocol 契约。
"""

import json
import logging
import math
import time
from collections.abc import AsyncGenerator
from typing import Any, Protocol, cast
from urllib.parse import urljoin

import anyio
import httpx
from pydantic import ValidationError

from mcp.client.auth._oauth_401_flow import oauth_401_flow_generator
from mcp.client.auth.oauth2 import OAuthClientProvider, TokenStorage as OAuth2TokenStorage
from mcp.client.auth.protocol import AuthContext, AuthProtocol, DPoPEnabledProtocol
from mcp.client.streamable_http import MCP_PROTOCOL_VERSION
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
from mcp.shared.auth import (
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthCredentials,
    OAuthToken,
    ProtectedResourceMetadata,
)

logger = logging.getLogger(__name__)

# Protocol preferences: any protocol without an explicit preference should sort last.
UNSPECIFIED_PROTOCOL_PREFERENCE: float = math.inf


class TokenStorage(Protocol):
    """
    凭证存储协议（multi_protocol 契约）。

    本协议接受 get_tokens() -> AuthCredentials | OAuthToken | None 与
    set_tokens(AuthCredentials | OAuthToken)。仅支持 OAuthToken 的旧存储亦可使用：
    MultiProtocolAuthProvider 在 _get_credentials/_discover_and_authenticate 内做
    OAuthToken <-> OAuthCredentials 转换；或使用 OAuthTokenStorageAdapter 包装。
    """

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        """获取已存储的凭证。"""
        ...

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        """存储凭证。"""
        ...


def _oauth_token_to_credentials(token: OAuthToken) -> OAuthCredentials:
    """将 OAuthToken 转为 OAuthCredentials（用于兼容现有存储）。"""
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
    """
    将 AuthCredentials 转为存储可接受格式，便于兼容仅支持 OAuthToken 的旧存储。
    OAuthCredentials 转为 OAuthToken；其他凭证原样返回。
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
    """仅支持 OAuthToken 的存储契约（供 OAuthTokenStorageAdapter 包装）。"""

    async def get_tokens(self) -> OAuthToken | None:
        ...

    async def set_tokens(self, tokens: OAuthToken) -> None:
        ...


class OAuthTokenStorageAdapter:
    """
    将仅支持 OAuthToken 的 storage 包装为满足 multi_protocol TokenStorage。

    取回时把 OAuthToken 转为 OAuthCredentials；写入时把 OAuthCredentials 转为 OAuthToken
    再调用底层 set_tokens。仅 OAuth 凭证会写入底层存储，非 OAuth 凭证（如 APIKeyCredentials）
    不写入。
    """

    def __init__(self, wrapped: _OAuthTokenOnlyStorage) -> None:
        self._wrapped = wrapped

    async def get_tokens(self) -> AuthCredentials | OAuthToken | None:
        raw = await self._wrapped.get_tokens()
        if raw is None:
            return None
        return _oauth_token_to_credentials(raw)

    async def set_tokens(self, tokens: AuthCredentials | OAuthToken) -> None:
        to_store = (
            _credentials_to_storage(tokens)
            if isinstance(tokens, AuthCredentials)
            else tokens
        )
        if isinstance(to_store, OAuthToken):
            await self._wrapped.set_tokens(to_store)


class MultiProtocolAuthProvider(httpx.Auth):
    """
    多协议认证提供者。

    与 httpx 集成，在请求前按所选协议准备认证信息，收到 401/403 时触发发现与认证。
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
        """根据 protocols 列表构建按 protocol_id 的索引。"""
        self._protocols_by_id = {p.protocol_id: p for p in self.protocols}
        self._initialized = True

    def _get_protocol(self, protocol_id: str) -> AuthProtocol | None:
        """按 protocol_id 获取协议实例。"""
        return self._protocols_by_id.get(protocol_id)

    async def _get_credentials(self) -> AuthCredentials | None:
        """
        从存储获取凭证并规范为 AuthCredentials。

        若存储返回 OAuthToken，则转换为 OAuthCredentials 以保持兼容。
        """
        raw = await self.storage.get_tokens()
        if raw is None:
            return None
        if isinstance(raw, AuthCredentials):
            return raw
        # raw 此时为 OAuthToken（TokenStorage 返回 AuthCredentials | OAuthToken | None）
        return _oauth_token_to_credentials(raw)

    def _is_credentials_valid(self, credentials: AuthCredentials | None) -> bool:
        """判断凭证是否有效（未过期等），依赖协议实现。"""
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
        """为请求添加协议指定的认证信息，包括 DPoP proof（如启用）。"""
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
        """解析 .well-known/authorization_servers 响应，回退到 PRM。"""
        if response.status_code == 200:
            try:
                content = await response.aread()
                data = json.loads(content.decode())
                raw = data.get("protocols")
                protocols_data: list[dict[str, Any]] = (
                    cast(list[dict[str, Any]], raw) if isinstance(raw, list) else []
                )
                if protocols_data:
                    return [AuthProtocolMetadata.model_validate(p) for p in protocols_data]
            except (ValidationError, ValueError, KeyError, TypeError) as e:
                logger.debug("Unified authorization_servers parse failed: %s", e)
        if prm is not None and prm.mcp_auth_protocols:
            return list(prm.mcp_auth_protocols)
        return []

    async def _handle_403_response(
        self, response: httpx.Response, request: httpx.Request
    ) -> None:
        """处理 403：解析 error/scope 并记录，骨架不做重试。"""
        error = extract_field_from_www_auth(response, "error")
        scope = extract_field_from_www_auth(response, "scope")
        if error or scope:
            logger.debug("403 WWW-Authenticate: error=%s scope=%s", error, scope)

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX 认证流程入口：取凭证、校验、准备请求、发送、处理 401/403 并可选重试。"""
        async with self._lock:
            if not self._initialized:
                self._initialize()

            credentials = await self._get_credentials()
            if not credentials or not self._is_credentials_valid(credentials):
                # 无有效凭证时直接发送请求，依赖 401 响应后再做发现与认证（见下方 401 处理）
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
                prm_urls = build_protected_resource_metadata_discovery_urls(
                    resource_metadata_url, server_url
                )
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
                protocols_metadata = await self._parse_protocols_from_discovery_response(
                    discovery_resp, prm
                )

                available = (
                    [m.protocol_id for m in protocols_metadata]
                    if protocols_metadata
                    else (auth_protocols_header or [])
                )
                if not available:
                    logger.debug("No available protocols from discovery or WWW-Authenticate")
                else:
                    # Select protocol candidates based on server hints, but only
                    # attempt protocols that are actually injected as instances.
                    candidates: list[str] = []
                    seen: set[str] = set()

                    def _push(pid: str | None) -> None:
                        if not pid:
                            return
                        if pid in seen:
                            return
                        seen.add(pid)
                        candidates.append(pid)

                    # Default protocol first (server recommendation)
                    _push(default_protocol)
                    # Then order by preferences if provided
                    if protocol_preferences:
                        for pid in sorted(
                            available,
                            key=lambda p: protocol_preferences.get(
                                p, UNSPECIFIED_PROTOCOL_PREFERENCE
                            ),
                        ):
                            _push(pid)
                    # Then remaining in server-provided order
                    for pid in available:
                        _push(pid)

                    for selected_id in candidates:
                        protocol = self._get_protocol(selected_id)
                        if protocol is None:
                            logger.debug(
                                "Protocol %s not injected as instance; skipping", selected_id
                            )
                            continue
                        attempted_any = True

                        protocol_metadata = None
                        if protocols_metadata:
                            for m in protocols_metadata:
                                if m.protocol_id == selected_id:
                                    protocol_metadata = m
                                    break

                        try:
                            if selected_id == "oauth2":
                                # OAuth: drive shared generator (single client, yield)
                                oauth_protocol = protocol
                                provider = OAuthClientProvider(
                                    server_url=server_url,
                                    client_metadata=getattr(
                                        oauth_protocol, "_client_metadata"
                                    ),
                                    storage=cast(OAuth2TokenStorage, self.storage),
                                    redirect_handler=getattr(
                                        oauth_protocol, "_redirect_handler", None
                                    ),
                                    callback_handler=getattr(
                                        oauth_protocol, "_callback_handler", None
                                    ),
                                    timeout=getattr(
                                        oauth_protocol, "_timeout", self.timeout
                                    ),
                                    client_metadata_url=getattr(
                                        oauth_protocol, "_client_metadata_url", None
                                    ),
                                )
                                provider.context.protocol_version = request.headers.get(
                                    MCP_PROTOCOL_VERSION
                                )
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
                                    scope_from_www_auth=extract_scope_from_www_auth(
                                        original_401_response
                                    ),
                                )
                                credentials = await protocol.authenticate(context)
                                to_store = _credentials_to_storage(credentials)
                                await self.storage.set_tokens(to_store)

                            # Stop after first successful protocol path that stores credentials
                            break
                        except Exception as e:
                            last_auth_error = e
                            logger.debug(
                                "Protocol %s authentication failed: %s", selected_id, e
                            )
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
