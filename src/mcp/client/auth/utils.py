import re
from urllib.parse import urljoin, urlparse

from httpx import Request, Response
from mcp_types import LATEST_PROTOCOL_VERSION
from pydantic import AnyUrl, ValidationError

from mcp.client.auth import OAuthFlowError, OAuthRegistrationError, OAuthTokenError
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER


def extract_field_from_www_auth(response: Response, field_name: str) -> str | None:
    """Extract a field value from the WWW-Authenticate header, or None if absent."""
    www_auth_header = response.headers.get("WWW-Authenticate")
    if not www_auth_header:
        return None

    # Matches field_name="value" or field_name=value (unquoted)
    pattern = rf'{field_name}=(?:"([^"]+)"|([^\s,]+))'
    match = re.search(pattern, www_auth_header)

    if match:
        return match.group(1) or match.group(2)

    return None


def extract_scope_from_www_auth(response: Response) -> str | None:
    """Extract the scope parameter from the WWW-Authenticate header (RFC 6750)."""
    return extract_field_from_www_auth(response, "scope")


def extract_resource_metadata_from_www_auth(response: Response) -> str | None:
    """Extract the protected resource metadata URL from the WWW-Authenticate header (RFC 9728)."""
    if not response or response.status_code != 401:
        return None  # pragma: no cover

    return extract_field_from_www_auth(response, "resource_metadata")


def build_protected_resource_metadata_discovery_urls(www_auth_url: str | None, server_url: str) -> list[str]:
    """Build the ordered list of URLs to try for protected resource metadata discovery.

    Per SEP-985: the WWW-Authenticate `resource_metadata` URL first (if present), then the
    path-based well-known URI, then the root-based well-known URI (RFC 9728).
    """
    urls: list[str] = []

    if www_auth_url:
        urls.append(www_auth_url)

    parsed = urlparse(server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    if parsed.path and parsed.path != "/":
        path_based_url = urljoin(base_url, f"/.well-known/oauth-protected-resource{parsed.path}")
        urls.append(path_based_url)

    root_based_url = urljoin(base_url, "/.well-known/oauth-protected-resource")
    urls.append(root_based_url)

    return urls


def get_client_metadata_scopes(
    www_authenticate_scope: str | None,
    protected_resource_metadata: ProtectedResourceMetadata | None,
    authorization_server_metadata: OAuthMetadata | None = None,
    client_grant_types: list[str] | None = None,
) -> str | None:
    """Select effective scopes and augment for refresh token support."""
    selected_scope: str | None = None

    # MCP spec scope priority: WWW-Authenticate scope > PRM scopes_supported > AS scopes_supported > omit
    if www_authenticate_scope is not None:
        selected_scope = www_authenticate_scope
    elif protected_resource_metadata is not None and protected_resource_metadata.scopes_supported is not None:
        selected_scope = " ".join(protected_resource_metadata.scopes_supported)
    elif authorization_server_metadata is not None and authorization_server_metadata.scopes_supported is not None:
        selected_scope = " ".join(authorization_server_metadata.scopes_supported)

    # SEP-2207: append offline_access when the AS supports it and the client can use refresh tokens
    if (
        selected_scope is not None
        and authorization_server_metadata is not None
        and authorization_server_metadata.scopes_supported is not None
        and "offline_access" in authorization_server_metadata.scopes_supported
        and client_grant_types is not None
        and "refresh_token" in client_grant_types
        and "offline_access" not in selected_scope.split()
    ):
        selected_scope = f"{selected_scope} offline_access"

    return selected_scope


def union_scopes(previous_scope: str | None, new_scope: str | None) -> str | None:
    """Merge two space-delimited scope strings, preserving order and dropping duplicates.

    SEP-2350: on step-up re-authorization the client requests the union of previously requested
    and newly challenged scopes, so escalating one operation does not drop permissions granted
    for another.
    """
    if not previous_scope:
        return new_scope
    if not new_scope:
        return previous_scope

    merged = previous_scope.split()
    seen = set(merged)
    for scope in new_scope.split():
        if scope not in seen:
            merged.append(scope)
            seen.add(scope)
    return " ".join(merged)


def build_oauth_authorization_server_metadata_discovery_urls(auth_server_url: str | None, server_url: str) -> list[str]:
    """Generate an ordered list of URLs for authorization server metadata discovery."""

    if not auth_server_url:
        # Legacy 2025-03-26 spec path: https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization
        parsed = urlparse(server_url)
        return [f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"]

    urls: list[str] = []
    parsed = urlparse(auth_server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # RFC 8414: path-aware OAuth discovery
    if parsed.path and parsed.path != "/":
        oauth_path = f"/.well-known/oauth-authorization-server{parsed.path.rstrip('/')}"
        urls.append(urljoin(base_url, oauth_path))

        # RFC 8414 section 5: path-aware OIDC discovery
        oidc_path = f"/.well-known/openid-configuration{parsed.path.rstrip('/')}"
        urls.append(urljoin(base_url, oidc_path))

        # OIDC discovery 1.0: well-known suffix appended after the path
        oidc_path = f"{parsed.path.rstrip('/')}/.well-known/openid-configuration"
        urls.append(urljoin(base_url, oidc_path))
        return urls

    urls.append(urljoin(base_url, "/.well-known/oauth-authorization-server"))

    # OIDC 1.0 fallback (https://openid.net/specs/openid-connect-discovery-1_0.html)
    urls.append(urljoin(base_url, "/.well-known/openid-configuration"))

    return urls


async def handle_protected_resource_response(
    response: Response,
) -> ProtectedResourceMetadata | None:
    """Parse a protected resource metadata discovery response.

    Returns None when discovery failed at this URL and the next one should be tried (SEP-985).
    """
    if response.status_code == 200:
        try:
            content = await response.aread()
            metadata = ProtectedResourceMetadata.model_validate_json(content)
            return metadata

        except ValidationError:  # pragma: no cover
            return None
    else:
        return None


async def handle_auth_metadata_response(response: Response) -> tuple[bool, OAuthMetadata | None]:
    if response.status_code == 200:
        try:
            content = await response.aread()
            asm = OAuthMetadata.model_validate_json(content)
            return True, asm
        except ValidationError:  # pragma: no cover
            return True, None
    elif response.status_code < 400 or response.status_code >= 500:
        return False, None  # Non-4XX error, stop trying
    return True, None


def validate_authorization_response_iss(iss: str | None, oauth_metadata: OAuthMetadata | None) -> None:
    """Validate the RFC 9207 `iss` authorization-response parameter.

    Per RFC 9207 section 2.4, `iss` is compared to the issuer of the authorization server the
    request was sent to by simple string comparison (RFC 3986 section 6.2.1); a missing `iss` is
    rejected only when the server advertised `authorization_response_iss_parameter_supported`.

    Raises:
        OAuthFlowError: On mismatch, or when `iss` is absent but the server advertised support.
    """
    expected = str(oauth_metadata.issuer) if oauth_metadata else None

    if iss is not None:
        if iss != expected:
            raise OAuthFlowError(f"Authorization response iss mismatch: {iss} != {expected}")
        return

    if oauth_metadata is not None and oauth_metadata.authorization_response_iss_parameter_supported:
        raise OAuthFlowError("Authorization response missing iss parameter advertised by the authorization server")


def validate_metadata_issuer(oauth_metadata: OAuthMetadata, expected_issuer: str) -> None:
    """Validate that authorization server metadata `issuer` matches the discovery issuer.

    RFC 8414 section 3.3 / SEP-2468: compared as a simple string (RFC 3986 section 6.2.1) against
    the issuer used to construct the well-known URL.

    Raises:
        OAuthFlowError: If the metadata issuer does not match `expected_issuer`.
    """
    if str(oauth_metadata.issuer) != expected_issuer:
        raise OAuthFlowError(
            f"Authorization server metadata issuer mismatch: {oauth_metadata.issuer} != {expected_issuer}"
        )


def create_oauth_metadata_request(url: str) -> Request:
    return Request("GET", url, headers={MCP_PROTOCOL_VERSION_HEADER: LATEST_PROTOCOL_VERSION})


def create_client_registration_request(
    auth_server_metadata: OAuthMetadata | None, client_metadata: OAuthClientMetadata, auth_base_url: str
) -> Request:
    if auth_server_metadata and auth_server_metadata.registration_endpoint:
        registration_url = str(auth_server_metadata.registration_endpoint)
    else:
        registration_url = urljoin(auth_base_url, "/register")

    registration_data = client_metadata.model_dump(by_alias=True, mode="json", exclude_none=True)

    return Request("POST", registration_url, json=registration_data, headers={"Content-Type": "application/json"})


async def handle_registration_response(response: Response) -> OAuthClientInformationFull:
    if response.status_code not in (200, 201):
        await response.aread()
        raise OAuthRegistrationError(f"Registration failed: {response.status_code} {response.text}")

    try:
        content = await response.aread()
        client_info = OAuthClientInformationFull.model_validate_json(content)
        return client_info
    except ValidationError as e:  # pragma: no cover
        raise OAuthRegistrationError(f"Invalid registration response: {e}")


def is_valid_client_metadata_url(url: str | None) -> bool:
    """Whether `url` is usable as a URL-based client ID (CIMD): HTTPS with a non-root path."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.path not in ("", "/")
    except Exception:
        return False


def credentials_match_issuer(
    client_info: OAuthClientInformationFull, issuer: str, client_metadata_url: str | None
) -> bool:
    """Whether stored client credentials may be reused against `issuer` (SEP-2352).

    A CIMD client ID is portable across authorization servers, so it always matches; CIMD is
    identified by the client ID equalling the configured `client_metadata_url`, not by URL shape
    (registration servers may also issue URL-shaped IDs bound to them). A recorded issuer must
    equal `issuer` (simple string comparison); credentials with no recorded issuer (pre-registered,
    or stored before issuer binding existed) carry no binding to enforce.
    """
    if client_metadata_url is not None and client_info.client_id == client_metadata_url:
        return True
    if client_info.issuer is None:
        return True
    return client_info.issuer == issuer


def should_use_client_metadata_url(
    oauth_metadata: OAuthMetadata | None,
    client_metadata_url: str | None,
) -> bool:
    """Whether to use a URL-based client ID (CIMD) instead of dynamic client registration."""
    if not client_metadata_url:
        return False

    if not oauth_metadata:
        return False

    return oauth_metadata.client_id_metadata_document_supported is True


def create_client_info_from_metadata_url(
    client_metadata_url: str, redirect_uris: list[AnyUrl] | None = None
) -> OAuthClientInformationFull:
    """Create client information using a URL-based client ID (CIMD).

    The URL itself becomes the client_id and no client_secret is used
    (`token_endpoint_auth_method="none"`).
    """
    return OAuthClientInformationFull(
        client_id=client_metadata_url,
        token_endpoint_auth_method="none",
        redirect_uris=redirect_uris,
    )


async def handle_token_response_scopes(
    response: Response,
) -> OAuthToken:
    """Parse and validate a token response; callers must check `response.status_code` first.

    Raises:
        OAuthTokenError: If the response JSON is invalid.
    """
    try:
        content = await response.aread()
        token_response = OAuthToken.model_validate_json(content)
        return token_response
    except ValidationError as e:  # pragma: no cover
        raise OAuthTokenError(f"Invalid token response: {e}")
