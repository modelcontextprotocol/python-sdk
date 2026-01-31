"""
OAuth 2.0 协议薄适配层。

不迁移 OAuth 发现/注册/授权码/令牌交换逻辑到此文件；
authenticate(context) 构造 OAuthClientProvider、填充上下文后调用
provider.run_authentication(context.http_client, ...)，返回 OAuthCredentials。
discover_metadata 在提供 http_client 时执行 RFC 8414 授权服务器元数据发现。
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import AnyHttpUrl

from mcp.client.auth.dpop import (
    RSA_KEY_SIZE_DEFAULT,
    DPoPAlgorithm,
    DPoPKeyPair,
    DPoPProofGeneratorImpl,
)
from mcp.client.auth.oauth2 import OAuthClientProvider
from mcp.client.auth.protocol import AuthContext, DPoPProofGenerator
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    create_oauth_metadata_request,
    handle_auth_metadata_response,
)
from mcp.shared.auth import (
    AuthCredentials,
    AuthProtocolMetadata,
    OAuthClientMetadata,
    OAuthCredentials,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)

logger = logging.getLogger(__name__)


def _oauth_metadata_to_protocol_metadata(asm: OAuthMetadata) -> AuthProtocolMetadata:
    """将 RFC 8414 OAuth 授权服务器元数据转换为 AuthProtocolMetadata。"""
    endpoints: dict[str, AnyHttpUrl] = {
        "authorization_endpoint": asm.authorization_endpoint,
        "token_endpoint": asm.token_endpoint,
    }

    if asm.registration_endpoint is not None:
        endpoints["registration_endpoint"] = asm.registration_endpoint
    if asm.revocation_endpoint is not None:
        endpoints["revocation_endpoint"] = asm.revocation_endpoint
    if asm.introspection_endpoint is not None:
        endpoints["introspection_endpoint"] = asm.introspection_endpoint
        
    return AuthProtocolMetadata(
        protocol_id="oauth2",
        protocol_version="2.0",
        metadata_url=asm.issuer,
        endpoints=endpoints,
        scopes_supported=asm.scopes_supported,
        grant_types=asm.grant_types_supported,
        client_auth_methods=asm.token_endpoint_auth_methods_supported,
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

    实现 AuthProtocol 和 DPoPEnabledProtocol，authenticate 委托 OAuthClientProvider.run_authentication，
    不重复实现 OAuth 流程。DPoP 支持通过 dpop_enabled 配置启用。
    """

    protocol_id: str = "oauth2"
    protocol_version: str = "2.0"

    def __init__(
        self,
        client_metadata: OAuthClientMetadata,
        redirect_handler: Callable[[str], Awaitable[None]] | None = None,
        callback_handler: Callable[[], Awaitable[tuple[str, str | None]]] | None = None,
        timeout: float = 300.0,
        client_metadata_url: str | None = None,
        dpop_enabled: bool = False,
        dpop_algorithm: DPoPAlgorithm = "ES256",
        dpop_rsa_key_size: int = RSA_KEY_SIZE_DEFAULT,
    ):
        self._client_metadata = client_metadata
        self._redirect_handler = redirect_handler
        self._callback_handler = callback_handler
        self._timeout = timeout
        self._client_metadata_url = client_metadata_url
        self._dpop_enabled = dpop_enabled
        self._dpop_algorithm: DPoPAlgorithm = dpop_algorithm
        self._dpop_rsa_key_size = dpop_rsa_key_size
        self._dpop_key_pair: DPoPKeyPair | None = None
        self._dpop_generator: DPoPProofGeneratorImpl | None = None

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
        http_client: httpx.AsyncClient | None = None,
    ) -> AuthProtocolMetadata | None:
        """
        发现 OAuth 2.0 协议元数据（RFC 8414）。

        若 prm 中已有 oauth2 的 mcp_auth_protocols 条目则直接返回；
        若提供 http_client 且存在 metadata_url 或 prm.authorization_servers，
        则按 RFC 8414 请求授权服务器元数据并转换为 AuthProtocolMetadata。
        """
        if prm is not None and prm.mcp_auth_protocols:
            for m in prm.mcp_auth_protocols:
                if m.protocol_id == "oauth2":
                    return m

        auth_server_url: str | None = metadata_url
        server_url_for_discovery: str = ""
        if prm is not None:
            if not auth_server_url and prm.authorization_servers:
                auth_server_url = str(prm.authorization_servers[0])
            server_url_for_discovery = str(prm.resource)
        if auth_server_url and not server_url_for_discovery:
            server_url_for_discovery = auth_server_url

        if not http_client or not auth_server_url:
            return None

        discovery_urls = build_oauth_authorization_server_metadata_discovery_urls(
            auth_server_url, server_url_for_discovery
        )
        for url in discovery_urls:
            try:
                req = create_oauth_metadata_request(url)
                resp = await http_client.send(req)
                ok, asm = await handle_auth_metadata_response(resp)
                if not ok:
                    break
                if asm is not None:
                    return _oauth_metadata_to_protocol_metadata(asm)
            except Exception as e:
                logger.debug("OAuth AS metadata discovery failed for %s: %s", url, e)
        return None

    # DPoPEnabledProtocol implementation

    def supports_dpop(self) -> bool:
        """Check if DPoP is enabled for this protocol instance."""
        return self._dpop_enabled

    def get_dpop_proof_generator(self) -> DPoPProofGenerator | None:
        """Get the DPoP proof generator if DPoP is initialized."""
        return self._dpop_generator

    async def initialize_dpop(self) -> None:
        """Initialize DPoP by generating a key pair and creating the proof generator."""
        if not self._dpop_enabled:
            return
        if self._dpop_key_pair is None:
            self._dpop_key_pair = DPoPKeyPair.generate(
                self._dpop_algorithm, rsa_key_size=self._dpop_rsa_key_size
            )
            self._dpop_generator = DPoPProofGeneratorImpl(self._dpop_key_pair)

    def get_dpop_public_key_jwk(self) -> dict[str, Any] | None:
        """Get the DPoP public key JWK for token binding (cnf.jkt)."""
        if self._dpop_generator is not None:
            return self._dpop_generator.get_public_key_jwk()
        return None
