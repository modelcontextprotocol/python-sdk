class UnauthorizedError(Exception):
    """Raised when the server responds with 401 and the auth provider cannot recover.

    Raised by `BearerAuth` when no `on_unauthorized` handler is configured, or when
    the single retry after `on_unauthorized` also receives 401. Callers can catch
    this to trigger an interactive re-authentication flow or surface a login prompt.
    """


class OAuthFlowError(Exception):
    """Base exception for OAuth flow errors."""


class OAuthTokenError(OAuthFlowError):
    """Raised when token operations fail."""


class OAuthRegistrationError(OAuthFlowError):
    """Raised when client registration fails."""
