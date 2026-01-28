"""
多协议认证提供者。

提供基于协议注册表与发现的统一 HTTP 认证流程，支持 OAuth 2.0、API Key 等协议。
"""

import logging
from collections.abc import AsyncGenerator
from typing import Any, Protocol

import anyio
import httpx

from mcp.client.auth.protocol import AuthProtocol
from mcp.client.auth.utils import (
    extract_auth_protocols_from_www_auth,
    extract_default_protocol_from_www_auth,
    extract_field_from_www_auth,
    extract_protocol_preferences_from_www_auth,
    extract_resource_metadata_from_www_auth,
)
from mcp.shared.auth import AuthCredentials, OAuthCredentials, OAuthToken

logger = logging.getLogger(__name__)


class TokenStorage(Protocol):
    """凭证存储协议（兼容 OAuthToken 与 AuthCredentials）。"""

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
        dpop_storage: Any = None,
        dpop_enabled: bool = False,
        timeout: float = 300.0,
    ):
        self.server_url = server_url
        self.storage = storage
        self.protocols = protocols or []
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

    def _prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        """为请求添加协议指定的认证信息（仅协议 prepare_request，不含 DPoP）。"""
        protocol = self._get_protocol(credentials.protocol_id)
        if protocol is not None:
            protocol.prepare_request(request, credentials)

    async def _discover_and_authenticate(
        self, request: httpx.Request, response: httpx.Response
    ) -> None:
        """
        根据 401 响应进行协议发现与认证，并将新凭证写入 storage。

        具体实现见 TODO 10（协议发现 + 注册表选择 + 协议 authenticate）。
        本骨架仅解析 WWW-Authenticate 并记录，不执行实际发现与认证。
        """
        resource_metadata_url = extract_resource_metadata_from_www_auth(response)
        auth_protocols = extract_auth_protocols_from_www_auth(response)
        default_protocol = extract_default_protocol_from_www_auth(response)
        protocol_preferences = extract_protocol_preferences_from_www_auth(response)
        if resource_metadata_url or auth_protocols or default_protocol or protocol_preferences:
            logger.debug(
                "401 WWW-Authenticate: resource_metadata=%s auth_protocols=%s default=%s preferences=%s",
                resource_metadata_url,
                auth_protocols,
                default_protocol,
                protocol_preferences,
            )

    async def _handle_401_response(
        self, response: httpx.Response, request: httpx.Request
    ) -> None:
        """处理 401：解析 WWW-Authenticate，触发发现与认证（骨架），便于后续重试。"""
        await self._discover_and_authenticate(request, response)

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
                self._prepare_request(request, credentials)

        response = yield request

        if response.status_code == 401:
            async with self._lock:
                await self._handle_401_response(response, request)
                credentials = await self._get_credentials()
                if credentials and self._is_credentials_valid(credentials):
                    self._prepare_request(request, credentials)
                    response = yield request
        elif response.status_code == 403:
            await self._handle_403_response(response, request)
