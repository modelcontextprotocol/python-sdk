"""
多协议凭证验证器。

提供 CredentialVerifier 协议及 OAuthTokenVerifier 实现，供 MultiProtocolAuthBackend 按协议尝试校验。
"""

from typing import Any, Protocol

from starlette.requests import Request

from mcp.server.auth.dpop import DPoPProofVerifier, DPoPVerificationError, extract_dpop_proof
from mcp.server.auth.provider import AccessToken, TokenVerifier

BEARER_PREFIX = "Bearer "
DPOP_PREFIX = "DPoP "
APIKEY_HEADER = "x-api-key"  # if found, use it; if not, use Authorization: Bearer <key>


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
    OAuth Bearer/DPoP 凭证验证器。

    支持 Bearer 和 DPoP 两种 token 类型。当提供 dpop_verifier 时，会验证 DPoP proof
    的签名、htm/htu/iat/ath 等声明。注：cnf.jkt 绑定检查暂未实现（需 AccessToken 扩展）。
    """

    def __init__(self, token_verifier: TokenVerifier) -> None:
        self._token_verifier = token_verifier

    async def verify(
        self,
        request: Request,
        dpop_verifier: Any = None,
    ) -> AccessToken | None:
        auth_header = _get_header_ignore_case(request, "authorization")
        if not auth_header:
            return None

        # Determine token type and extract token
        token: str | None = None
        is_dpop_bound = False

        if auth_header.lower().startswith(DPOP_PREFIX.lower()):
            # DPoP-bound access token (Authorization: DPoP <token>)
            token = auth_header[len(DPOP_PREFIX):].strip()
            is_dpop_bound = True
        elif auth_header.lower().startswith(BEARER_PREFIX.lower()):
            token = auth_header[len(BEARER_PREFIX):].strip()

        if not token:
            return None

        # Verify the token itself
        access_token = await self._token_verifier.verify_token(token)
        if access_token is None:
            return None

        # DPoP verification if verifier provided and DPoP header present
        if dpop_verifier is not None and isinstance(dpop_verifier, DPoPProofVerifier):
            headers_dict = dict(request.headers)
            dpop_proof = extract_dpop_proof(headers_dict)

            if is_dpop_bound and not dpop_proof:
                # DPoP-bound token requires DPoP proof
                return None

            if dpop_proof:
                try:
                    http_uri = str(request.url)
                    http_method = request.method

                    await dpop_verifier.verify(
                        dpop_proof,
                        http_method,
                        http_uri,
                        access_token=token,
                    )
                except DPoPVerificationError:
                    return None

        return access_token


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
    可选 scopes：校验通过时赋予的 scope 列表，用于满足 RequireAuthMiddleware 的 required_scopes。
    """

    def __init__(self, valid_keys: set[str], scopes: list[str] | None = None) -> None:
        self._valid_keys = valid_keys
        self._scopes = scopes if scopes is not None else []

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
            scopes=list(self._scopes),
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
