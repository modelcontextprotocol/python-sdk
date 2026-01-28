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

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """HTTPX 认证流程入口（骨架：取凭证、校验、准备请求、发送、处理 401/403）。"""
        async with self._lock:
            if not self._initialized:
                self._initialize()

            credentials = await self._get_credentials()
            if not credentials or not self._is_credentials_valid(credentials):
                # TODO (TODO 9/10): _discover_and_authenticate(request)
                pass
            else:
                self._prepare_request(request, credentials)

        response = yield request

        if response.status_code == 401:
            # TODO (TODO 9): _handle_401_response(response, request)
            pass
        elif response.status_code == 403:
            # TODO (TODO 9): _handle_403_response(response, request)
            pass
