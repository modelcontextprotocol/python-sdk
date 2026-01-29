"""
OAuth 2.0 协议薄适配层。

不迁移 OAuth 发现/注册/授权码/令牌交换逻辑到此文件；
authenticate(context) 构造 OAuthClientProvider、填充上下文后调用
provider.run_authentication(context.http_client, ...)，返回 OAuthCredentials。
"""

import time
from collections.abc import Awaitable, Callable

import httpx

from mcp.client.auth.oauth2 import OAuthClientProvider
from mcp.client.auth.protocol import AuthContext
from mcp.shared.auth import (
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthClientMetadata,
    OAuthCredentials,
    OAuthToken,
    ProtectedResourceMetadata,
)


def _token_to_oauth_credentials(token: OAuthToken) -> OAuthCredentials:
    """将 OAuthToken 转为 OAuthCredentials。"""
    from mcp.shared.auth_utils import calculate_token_expiry

    expires_at: int | None = None
    if token.expires_in is not None:
        expiry = calculate_token_expiry(token.expires_in)
        expires_at = int(expiry) if expiry is not None else None
    return OAuthCredentials.model_validate(
        {
            "protocol_id": "oauth2",
            "access_token": token.access_token,
            "token_type": token.token_type,
            "refresh_token": token.refresh_token,
            "scope": token.scope,
            "expires_at": expires_at,
        }
    )


class OAuth2Protocol:
    """
    OAuth 2.0 协议薄适配层。

    实现 AuthProtocol，authenticate 委托 OAuthClientProvider.run_authentication，
    不重复实现 OAuth 流程。
    """

    protocol_id: str = "oauth2"
    protocol_version: str = "1.0"

    def __init__(
        self,
        client_metadata: OAuthClientMetadata,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
        client_metadata_url: str | None = None,
    ):
        self._client_metadata = client_metadata
        self._redirect_handler = redirect_handler
        self._callback_handler = callback_handler
        self._timeout = timeout
        self._client_metadata_url = client_metadata_url

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        """从 AuthContext 组装 OAuth 上下文，委托 OAuthClientProvider.run_authentication，返回 OAuthCredentials。"""
        if context.http_client is None:
            raise ValueError("OAuth2Protocol.authenticate requires context.http_client")

        provider = OAuthClientProvider(
            server_url=context.server_url,
            client_metadata=self._client_metadata,
            storage=context.storage,
            redirect_handler=self._redirect_handler,
            callback_handler=self._callback_handler,
            timeout=self._timeout,
            client_metadata_url=self._client_metadata_url,
        )
        protocol_version: str | None = None
        if context.protocol_metadata is not None:
            protocol_version = getattr(
                context.protocol_metadata, "protocol_version", None
            )
        await provider.run_authentication(
            context.http_client,
            resource_metadata_url=context.resource_metadata_url,
            scope_from_www_auth=context.scope_from_www_auth,
            protocol_version=protocol_version,
            protected_resource_metadata=context.protected_resource_metadata,
        )
        if not provider.context.current_tokens:
            raise RuntimeError("run_authentication completed but no tokens in provider")
        return _token_to_oauth_credentials(provider.context.current_tokens)

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        """为请求添加 Bearer 认证头。"""
        if isinstance(credentials, OAuthCredentials) and credentials.access_token:
            request.headers["Authorization"] = f"Bearer {credentials.access_token}"

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        """验证 OAuth 凭证是否有效（未过期等）。"""
        if not isinstance(credentials, OAuthCredentials):
            return False
        if not credentials.access_token:
            return False
        if credentials.expires_at is not None and credentials.expires_at <= int(time.time()):
            return False
        return True

    async def discover_metadata(
        self,
        metadata_url: str | None = None,
        prm: ProtectedResourceMetadata | None = None,
    ) -> AuthProtocolMetadata | None:
        """发现协议元数据（RFC 8414）。TODO 23 中完善。"""
        return None
