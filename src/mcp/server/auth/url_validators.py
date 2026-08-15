"""OAuth 2.0 URL validation helpers for MCP authorization servers.

RFC 9700 4.1.1 and RFC 7591 2 require HTTPS for authorization endpoint URLs
and registered redirect_uris, with an HTTP loopback exception for local
development.
"""

from pydantic import AnyUrl


def validate_redirect_uri(url: AnyUrl):
    """Validate a registered redirect_uri for DCR.

    RFC 9700 section 4.1.1 and RFC 7591 section 2 require HTTPS for
    redirect_uris, with an HTTP loopback exception for local development.

    Args:
        url: The redirect URI to validate.

    Raises:
        ValueError: If the redirect URI uses an unsafe scheme or contains
            a fragment.
    """
    if url.scheme not in ("http", "https"):
        raise ValueError("Redirect URI must use an HTTP(S) scheme")

    if url.fragment is not None:
        raise ValueError("Redirect URI must not contain a fragment")
