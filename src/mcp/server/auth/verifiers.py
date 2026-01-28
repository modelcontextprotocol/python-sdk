"""
多协议凭证验证器。

提供 CredentialVerifier 协议及 OAuthTokenVerifier 实现，供 MultiProtocolAuthBackend 按协议尝试校验。
"""

from typing import Any, Protocol

from starlette.requests import Request

from mcp.server.auth.provider import AccessToken, TokenVerifier

BEARER_PREFIX = "Bearer "
BEARER_PREFIX_LENGTH = len(BEARER_PREFIX) # 7


class CredentialVerifier(Protocol):
    """凭证验证器协议：按请求校验认证信息，可选 DPoP 校验（阶段4 实现）。"""

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        """
        校验请求中的凭证。

        Args:
            request: 待校验的请求。
            dpop_verifier: 可选 DPoP 校验器，阶段4 再使用。

        Returns:
            校验成功时返回 AccessToken，否则返回 None。
        """
        ...


class OAuthTokenVerifier:
    """
    OAuth Bearer 凭证验证器。

    封装现有 TokenVerifier，仅做 Bearer 校验；DPoP 参数占位，阶段4 再实现。
    """

    def __init__(self, token_verifier: TokenVerifier) -> None:
        self._token_verifier = token_verifier

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        auth_header = next(
            (request.headers.get(key) for key in request.headers if key.lower() == "authorization"),
            None,
        )
        if not auth_header or not auth_header.lower().startswith(BEARER_PREFIX.lower()):
            return None
        token = auth_header[BEARER_PREFIX_LENGTH :].strip()
        if not token:
            return None
        return await self._token_verifier.verify_token(token)
