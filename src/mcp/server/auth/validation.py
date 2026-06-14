from pydantic import AnyHttpUrl, AnyUrl


def validate_issuer_url(url: AnyHttpUrl):
    """Validate that the issuer URL meets OAuth 2.0 requirements.

    Args:
        url: The issuer URL to validate.

    Raises:
        ValueError: If the issuer URL is invalid.
    """

    # RFC 8414 requires HTTPS, but we allow loopback/localhost HTTP for testing
    if url.scheme != "https" and url.host not in ("localhost", "127.0.0.1", "[::1]"):
        raise ValueError("Issuer URL must be HTTPS")

    # No fragments or query parameters allowed
    if url.fragment:
        raise ValueError("Issuer URL must not have a fragment")
    if url.query:
        raise ValueError("Issuer URL must not have a query string")


def validate_registered_redirect_uri(url: AnyUrl):
    """Validate that a dynamically registered redirect URI is safe to use.

    Mirrors the HTTPS-or-loopback policy used for issuer URLs and rejects
    dangerous schemes such as javascript:, data:, and file:.
    """
    if url.scheme not in ("https", "http"):
        raise ValueError("Redirect URI must use HTTPS or HTTP")

    if url.scheme != "https" and url.host not in ("localhost", "127.0.0.1", "[::1]"):
        raise ValueError("Redirect URI must be HTTPS unless loopback")

    if url.fragment:
        raise ValueError("Redirect URI must not have a fragment")
