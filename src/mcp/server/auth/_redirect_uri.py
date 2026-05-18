"""Internal helpers for validating registered OAuth redirect URIs.

Lives outside :mod:`mcp.server.auth.routes` to avoid a circular import:
``routes`` imports :class:`~mcp.server.auth.handlers.register.RegistrationHandler`,
and the handler in turn needs the redirect-URI validator, so the validator
must sit in a module that neither side has to depend on transitively.
:mod:`mcp.server.auth.routes` re-exports :func:`validate_registered_redirect_uri`
so callers (including tests) keep the public import path.
"""

from pydantic import AnyUrl

from mcp.shared.auth import InvalidRedirectUriError


def validate_registered_redirect_uri(url: AnyUrl) -> None:
    """Validate that a registered redirect_uri meets OAuth 2.0 + RFC 7591 requirements.

    Mirrors the policy that :func:`mcp.server.auth.routes.validate_issuer_url`
    applies to issuer URLs: redirect URIs must use ``https``, except that
    ``http`` is permitted for loopback hosts (``localhost``, ``127.0.0.1``,
    ``[::1]``) per RFC 8252 §7.3, and they MUST NOT carry a fragment component
    per RFC 7591 §2.

    Args:
        url: A registered redirect_uri value from
            :class:`mcp.shared.auth.OAuthClientMetadata`.

    Raises:
        InvalidRedirectUriError: If the URI uses a scheme other than ``https``
            or loopback ``http``, or if it contains a fragment.
    """
    # RFC 9700 §4.1.1 (OAuth 2.0 Security BCP): https-only, with the RFC 8252
    # native-app loopback exception.
    if url.scheme not in ("https", "http"):
        raise InvalidRedirectUriError(f"redirect_uri must use https (or http for loopback); got scheme {url.scheme!r}")
    if url.scheme == "http" and url.host not in ("localhost", "127.0.0.1", "[::1]"):
        raise InvalidRedirectUriError(f"redirect_uri must use https for non-loopback hosts; got {str(url)!r}")
    # RFC 7591 §2: redirect_uri MUST NOT contain a fragment component.
    if url.fragment is not None:
        raise InvalidRedirectUriError(f"redirect_uri must not have a fragment; got {str(url)!r}")
