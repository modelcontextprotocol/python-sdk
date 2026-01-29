"""
多协议凭证验证器。

提供 CredentialVerifier 协议及 OAuthTokenVerifier 实现，供 MultiProtocolAuthBackend 按协议尝试校验。
"""

from typing import Any, Protocol

from starlette.requests import Request

from mcp.server.auth.provider import AccessToken, TokenVerifier

BEARER_PREFIX = "Bearer "
APIKEY_HEADER = "x-api-key" # if found, use it; if not, use Authorization: Bearer <key>


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
        token = auth_header[len(BEARER_PREFIX) :].strip()
        if not token:
            return None
        return await self._token_verifier.verify_token(token)


def _get_header_ignore_case(request: Request, name: str) -> str | None:
    """Get first header value matching name (case-insensitive)."""
    for key in request.headers:
        if key.lower() == name.lower():
            return request.headers.get(key)
    return None


class APIKeyVerifier:
    """
    API Key 凭证验证器。

    优先从 X-API-Key header 读取；可选从 Authorization: Bearer <key> 读取并在 valid_keys 中查找。
    不解析非标准 ApiKey scheme；DPoP 占位，阶段4 再实现。
    """

    def __init__(self, valid_keys: set[str]) -> None:
        self._valid_keys = valid_keys

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        api_key: str | None = _get_header_ignore_case(request, APIKEY_HEADER)
        if not api_key:
            auth_header = _get_header_ignore_case(request, "authorization")
            if auth_header and auth_header.strip().lower().startswith(BEARER_PREFIX.lower()):
                bearer_token = auth_header[len(BEARER_PREFIX) :].strip()
                if bearer_token in self._valid_keys:
                    api_key = bearer_token
        if not api_key or api_key not in self._valid_keys:
            return None
        return AccessToken(
            token=api_key,
            client_id="api_key",
            scopes=[],
            expires_at=None,
        )


class MultiProtocolAuthBackend:
    """
    多协议认证后端。

    按顺序遍历 verifiers，第一个校验成功的返回其 AccessToken，否则返回 None。
    """

    def __init__(self, verifiers: list[CredentialVerifier]) -> None:
        self._verifiers = verifiers

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        for verifier in self._verifiers:
            result = await verifier.verify(request, dpop_verifier)
            if result is not None:
                return result
        return None
