"""
授权协议抽象接口定义。

提供多协议授权支持的统一接口抽象。
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from mcp.shared.auth import AuthCredentials, AuthProtocolMetadata, ProtectedResourceMetadata


# DPoP相关类型占位符（阶段4实现）
class DPoPStorage(Protocol):
    """DPoP密钥对存储接口（阶段4实现）"""

    async def get_key_pair(self, protocol_id: str) -> Any: ...
    async def set_key_pair(self, protocol_id: str, key_pair: Any) -> None: ...


class DPoPProofGenerator(Protocol):
    """DPoP证明生成器接口（阶段4实现）"""

    def generate_proof(self, method: str, uri: str, credential: str | None = None, nonce: str | None = None) -> str: ...
    def get_public_key_jwk(self) -> dict[str, Any]: ...


class ClientRegistrationResult(Protocol):
    """客户端注册结果接口"""

    client_id: str
    client_secret: str | None = None


@dataclass
class AuthContext:
    """通用认证上下文"""

    server_url: str
    storage: Any  # TokenStorage协议类型
    protocol_id: str
    protocol_metadata: AuthProtocolMetadata | None = None
    current_credentials: AuthCredentials | None = None
    dpop_storage: DPoPStorage | None = None
    dpop_enabled: bool = False
    # 供 OAuth2Protocol.run_authentication 使用（多协议路径，与 401 分支一致）
    http_client: httpx.AsyncClient | None = None
    resource_metadata_url: str | None = None
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    scope_from_www_auth: str | None = None


class AuthProtocol(Protocol):
    """授权协议基础接口（所有协议必须实现）"""

    protocol_id: str
    protocol_version: str

    async def authenticate(self, context: AuthContext) -> AuthCredentials:
        """
        执行认证流程，获取凭证。

        Args:
            context: 认证上下文

        Returns:
            认证凭证
        """
        ...

    def prepare_request(self, request: httpx.Request, credentials: AuthCredentials) -> None:
        """
        准备HTTP请求，添加认证信息。

        Args:
            request: HTTP请求对象
            credentials: 认证凭证
        """
        ...

    def validate_credentials(self, credentials: AuthCredentials) -> bool:
        """
        验证凭证是否有效（未过期等）。

        Args:
            credentials: 待验证的凭证

        Returns:
            True if credentials are valid, False otherwise
        """
        ...

    async def discover_metadata(
        self, metadata_url: str | None, prm: ProtectedResourceMetadata | None = None
    ) -> AuthProtocolMetadata | None:
        """
        发现协议元数据。

        Args:
            metadata_url: 元数据URL（可选）
            prm: 受保护资源元数据（可选）

        Returns:
            协议元数据，如果发现失败则返回None
        """
        ...


class ClientRegisterableProtocol(AuthProtocol):
    """支持客户端注册的协议扩展接口"""

    async def register_client(self, context: AuthContext) -> ClientRegistrationResult | None:
        """
        注册客户端。

        Args:
            context: 认证上下文

        Returns:
            客户端注册结果，如果注册失败或不需要注册则返回None
        """
        ...


class DPoPEnabledProtocol(AuthProtocol):
    """支持DPoP的协议扩展接口（阶段4实现）"""

    def supports_dpop(self) -> bool:
        """
        检查协议是否支持DPoP。

        Returns:
            True if protocol supports DPoP, False otherwise
        """
        ...

    def get_dpop_proof_generator(self) -> DPoPProofGenerator | None:
        """
        获取DPoP证明生成器。

        Returns:
            DPoP证明生成器，如果协议不支持DPoP则返回None
        """
        ...

    async def initialize_dpop(self) -> None:
        """
        初始化DPoP（生成密钥对等）。

        仅在协议支持DPoP时调用。
        """
        ...
