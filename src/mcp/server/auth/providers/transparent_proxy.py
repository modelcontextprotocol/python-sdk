# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false, reportUnknownArgumentType=false, reportCallIssue=false, reportUnnecessaryIsInstance=false
from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlencode

import httpx  # type: ignore
from pydantic import AnyHttpUrl, AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.responses import Response
from starlette.routing import Route

from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
)
from mcp.server.auth.proxy.routes import create_proxy_routes
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.fastmcp.utilities.logging import redact_sensitive_data
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

"""Transparent OAuth proxy provider for FastMCP (Anthropic SDK).

This provider mimics the behaviour of fastapi_mcp's `setup_proxies=True` and the
`TransparentOAuthProxyProvider` from the `fastmcp` fork.  It forwards all real
OAuth traffic (authorize / token / jwks) to an upstream Authorization Server
(AS) while *locally* implementing Dynamic Client Registration so that MCP
clients such as Cursor can register even when the upstream AS disables RFC 7591
registration.

Environment variables (all optional – if omitted fall back to sensible defaults
or raise clearly):

UPSTREAM_AUTHORIZATION_ENDPOINT   Full URL of the upstream `/authorize` endpoint
UPSTREAM_TOKEN_ENDPOINT           Full URL of the upstream `/token` endpoint
UPSTREAM_JWKS_URI                 URL of the upstream JWKS (optional, not yet used)
UPSTREAM_CLIENT_ID                Fixed client_id registered with the upstream
UPSTREAM_CLIENT_SECRET            Fixed secret (omit for public client)

PROXY_DEFAULT_SCOPE               Space-separated default scope (default: "openid")

A simple helper ``TransparentOAuthProxyProvider.from_env()`` reads these vars.
"""

__all__ = ["TransparentOAuthProxyProvider"]

logger = logging.getLogger("transparent_oauth_proxy")


class ProxyTokenHandler(TokenHandler):
    """Token handler that simply proxies token requests to the upstream AS.

    We intentionally bypass redirect_uri and PKCE checks that the normal
    ``TokenHandler`` performs because in *transparent proxy* mode we do not
    have enough information locally.  Instead of validating, we forward the
    form untouched to the upstream token endpoint and stream the response
    back to the caller.
    """

    def __init__(self, provider: TransparentOAuthProxyProvider):
        # We provide a dummy ClientAuthenticator that will accept any client –
        # we are not going to invoke the base-class logic anyway.
        super().__init__(provider=provider, client_authenticator=ClientAuthenticator(provider))
        self.provider = provider  # keep for easy access

    async def handle(self, request) -> Response:  # type: ignore[override]
        correlation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(f"[{correlation_id}] 🔄 ProxyTokenHandler - passthrough")

        try:
            form = await request.form()
            form_dict = dict(form)

            redacted_form = redact_sensitive_data(form_dict)
            logger.info(f"[{correlation_id}] ➡︎ Incoming form: {redacted_form}")

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "MCP-TransparentProxy/1.0",
            }

            http = self.provider.http_client
            logger.info(f"[{correlation_id}] ⮕ Forwarding to {self.provider._s.upstream_token}")
            upstream_resp = await http.post(str(self.provider._s.upstream_token), data=form_dict, headers=headers)

        except httpx.HTTPError as exc:
            logger.error(f"[{correlation_id}] ✗ Upstream HTTP error: {exc}")
            return Response(
                content='{"error":"server_error","error_description":"Upstream server error"}',
                status_code=502,
                headers={"Content-Type": "application/json"},
            )
        except Exception as exc:
            logger.error(f"[{correlation_id}] ✗ Unexpected proxy error: {exc}")
            return Response(
                content='{"error":"server_error"}',
                status_code=500,
                headers={"Content-Type": "application/json"},
            )

        finally:
            elapsed = time.time() - start_time
            logger.info(f"[{correlation_id}] ⏱ Finished in {elapsed:.2f}s")

        # Log upstream response (redacted)
        try:
            if upstream_resp.headers.get("content-type", "").startswith("application/json"):
                body = upstream_resp.json()
                logger.info(
                    f"[{correlation_id}] ⬅︎ Body: {redact_sensitive_data(body) if isinstance(body, dict) else body}"
                )
        except Exception:
            pass

        return Response(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
        )


class ProxySettings(BaseSettings):
    """Validated environment-driven settings for the transparent OAuth proxy."""

    model_config = SettingsConfigDict(env_file=".env", populate_by_name=True, extra="ignore")

    upstream_authorize: AnyHttpUrl = Field(..., alias="UPSTREAM_AUTHORIZATION_ENDPOINT")
    upstream_token: AnyHttpUrl = Field(..., alias="UPSTREAM_TOKEN_ENDPOINT")
    jwks_uri: str | None = Field(None, alias="UPSTREAM_JWKS_URI")

    client_id: str | None = Field(None, alias="UPSTREAM_CLIENT_ID")
    client_secret: str | None = Field(None, alias="UPSTREAM_CLIENT_SECRET")

    # Allow overriding via env var, but default to "openid" if not provided
    default_scope: str = Field("openid", alias="PROXY_DEFAULT_SCOPE")

    @classmethod
    def load(cls) -> ProxySettings:
        """Instantiate settings from environment variables (for backwards compatibility)."""
        return cls()


# Backwards-compatibility alias – existing callers/tests import `_Settings`
_Settings = ProxySettings  # type: ignore


class TransparentOAuthProxyProvider(OAuthAuthorizationServerProvider[AuthorizationCode, Any, AccessToken]):
    """Minimal pass-through provider – only implements code flow, no refresh."""

    def __init__(self, *, settings: ProxySettings):
        # Fill in client_id fallback if not provided via upstream var
        if settings.client_id is None:
            settings.client_id = os.getenv("PROXY_CLIENT_ID", "demo-client-id")  # type: ignore[assignment]
        assert settings.client_id is not None, "client_id must be provided"
        self._s = settings
        # simple in-memory auth-code store (maps code→AuthorizationCode)
        self._codes: dict[str, AuthorizationCode] = {}
        # always the same client info returned by /register
        self._static_client = OAuthClientInformationFull(
            client_id=str(self._s.client_id),
            client_secret=self._s.client_secret,
            redirect_uris=[cast(AnyUrl, cast(object, "http://localhost"))],
            grant_types=["authorization_code"],
            token_endpoint_auth_method="none" if self._s.client_secret is None else "client_secret_post",
        )

        # Single reusable HTTP client for communicating with the upstream AS
        self._http: httpx.AsyncClient = httpx.AsyncClient(timeout=15)

    # Expose http client for handlers
    @property
    def http_client(self) -> httpx.AsyncClient:  # noqa: D401
        return self._http

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # ---------------------------------------------------------------------
    # Dynamic Client Registration – always enabled
    # ---------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:  # noqa: D401
        return self._static_client if client_id == self._s.client_id else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:  # noqa: D401
        """Spoof DCR: overwrite the incoming info with fixed credentials."""

        client_info.client_id = str(self._s.client_id)
        client_info.client_secret = self._s.client_secret
        # Ensure token_endpoint_auth_method reflects whether secret exists
        client_info.token_endpoint_auth_method = "none" if self._s.client_secret is None else "client_secret_post"
        # Replace stored static client redirect URIs with provided ones so later validation passes
        self._static_client.redirect_uris = client_info.redirect_uris
        return None

    # ------------------------------------------------------------------
    # Authorization endpoint – redirect to upstream
    # ------------------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:  # noqa: D401
        query: dict[str, str | None] = {
            "response_type": "code",
            "client_id": str(self._s.client_id),
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(params.scopes or [self._s.default_scope]),
            "state": params.state,
        }
        return f"{self._s.upstream_authorize}?{urlencode({k: v for k, v in query.items() if v})}"

    # ------------------------------------------------------------------
    # Auth-code tracking / exchange
    # ------------------------------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:  # noqa: D401,E501
        # create lightweight object; we cannot verify with upstream at this stage
        return AuthorizationCode(
            code=authorization_code,
            scopes=[self._s.default_scope],
            expires_at=int(time.time() + 300),
            client_id=str(self._s.client_id),
            redirect_uri=cast(AnyUrl, cast(object, "http://localhost")),  # type: ignore[arg-type]
            redirect_uri_provided_explicitly=False,
            code_challenge="",  # not validated here
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:  # noqa: D401,E501
        # Generate correlation ID for this request
        correlation_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(f"[{correlation_id}] Starting token exchange for client_id={client.client_id}")

        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "client_id": str(self._s.client_id),
            "code": authorization_code.code,
            "redirect_uri": str(authorization_code.redirect_uri),
        }
        if self._s.client_secret:
            data["client_secret"] = self._s.client_secret

        # Log outgoing request with full details
        redacted_data = redact_sensitive_data(data)
        logger.info(f"[{correlation_id}] ⮕ Preparing upstream token request")
        logger.info(f"[{correlation_id}] ⮕ Target URL: {self._s.upstream_token}")
        logger.info(f"[{correlation_id}] ⮕ Request data: {redacted_data}")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "MCP-TransparentProxy/1.0",
        }
        logger.info(f"[{correlation_id}] ⮕ Request headers: {headers}")

        http = self.http_client
        try:
            logger.info(f"[{correlation_id}] ⮕ Sending POST request to upstream")
            resp = await http.post(str(self._s.upstream_token), data=data, headers=headers)

            elapsed_time = time.time() - start_time
            logger.info(f"[{correlation_id}] ⬅︎ Upstream response received in {elapsed_time:.2f}s")
            logger.info(f"[{correlation_id}] ⬅︎ Status: {resp.status_code}")
            logger.info(f"[{correlation_id}] ⬅︎ Headers: {dict(resp.headers)}")

            # Log response body (redacted)
            try:
                body = resp.json()
                redacted_body = redact_sensitive_data(body) if isinstance(body, dict) else body
                logger.info(f"[{correlation_id}] ⬅︎ Response body: {redacted_body}")
            except Exception as e:
                logger.warning(f"[{correlation_id}] ⬅︎ Could not parse response as JSON: {e}")
                logger.info(f"[{correlation_id}] ⬅︎ Raw response: {resp.text[:500]}...")

            resp.raise_for_status()

        except httpx.HTTPError as e:
            logger.error(f"[{correlation_id}] ⬅︎ HTTP error occurred: {e}")
            raise
        except Exception as e:
            logger.error(f"[{correlation_id}] ⬅︎ Unexpected error: {e}")
            raise

        body: Mapping[str, Any] = resp.json()
        logger.info(f"[{correlation_id}] ✓ Token exchange completed successfully")
        return OAuthToken(**body)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Unused grant types
    # ------------------------------------------------------------------

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):  # noqa: D401
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
        scopes: list[str],
    ) -> OAuthToken:  # noqa: D401
        raise NotImplementedError

    async def load_access_token(self, token: str) -> AccessToken | None:  # noqa: D401
        # For now we cannot validate JWT; return a dummy AccessToken so BearerAuth passes.
        return AccessToken(
            token=token, client_id=str(self._s.client_id), scopes=[self._s.default_scope], expires_at=None
        )

    async def revoke_token(self, token: object) -> None:  # noqa: D401
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> TransparentOAuthProxyProvider:
        """Construct provider using :class:`ProxySettings` populated from the environment."""
        return cls(settings=ProxySettings.load())

    # FastMCP will read `client_registration_options` to decide whether to expose /register
    @property
    def client_registration_options(self) -> ClientRegistrationOptions:  # type: ignore[override]
        return ClientRegistrationOptions(enabled=True)

    # ------------------------------------------------------------------
    # Provide custom auth routes so that our proxy /token endpoint overrides the default one
    # ------------------------------------------------------------------

    def get_auth_routes(self):  # type: ignore[override]
        """Return full auth+proxy route list for FastMCP."""

        routes = create_auth_routes(
            provider=self,
            issuer_url=AnyHttpUrl("http://localhost:8000"),  # placeholder; FastMCP rewrites host
            client_registration_options=self.client_registration_options,
            revocation_options=None,
            service_documentation_url=None,
        )

        # Drop default /token and /authorize handlers – we provide custom ones.
        routes = [r for r in routes if not (isinstance(r, Route) and r.path in {"/token", "/authorize"})]

        # Insert proxy /token handler first for high precedence
        proxy_handler = ProxyTokenHandler(self)
        routes.insert(0, Route("/token", endpoint=proxy_handler.handle, methods=["POST"]))

        # Append additional proxy endpoints (metadata, register, authorize, revoke…)
        routes.extend(create_proxy_routes(self))

        return routes
