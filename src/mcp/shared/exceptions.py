from __future__ import annotations

from typing import Any, cast

from mcp_types import INVALID_REQUEST, URL_ELICITATION_REQUIRED, ElicitRequestURLParams, ErrorData, JSONRPCError


class MCPDeprecationWarning(UserWarning):
    """A custom deprecation warning for the MCP SDK.

    Unlike the built-in `DeprecationWarning`, this inherits from `UserWarning` so
    it is shown by default, helping users discover deprecated features without
    enabling warnings explicitly.

    Reference: https://sethmlarson.dev/deprecations-via-warnings-dont-work-for-python-libraries
    """


class MCPError(Exception):
    """Exception type raised when an error arrives over an MCP connection."""

    error: ErrorData

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(code, message, data)
        if data is not None:
            self.error = ErrorData(code=code, message=message, data=data)
        else:
            self.error = ErrorData(code=code, message=message)

    @property
    def code(self) -> int:
        return self.error.code

    @property
    def message(self) -> str:
        return self.error.message

    @property
    def data(self) -> Any:
        return self.error.data  # pragma: no cover

    @classmethod
    def from_jsonrpc_error(cls, error: JSONRPCError) -> MCPError:
        return cls.from_error_data(error.error)

    @classmethod
    def from_error_data(cls, error: ErrorData) -> MCPError:
        return cls(code=error.code, message=error.message, data=error.data)

    def __str__(self) -> str:
        return self.message


class NoBackChannelError(MCPError):
    """Raised when sending a server-initiated request over a transport that cannot deliver it.

    Stateless HTTP and JSON-response-mode HTTP have no channel for the server to
    push requests (sampling, elicitation, roots/list) to the client. This is
    raised by `DispatchContext.send_raw_request` when `can_send_request` is
    `False`, and serializes to an `INVALID_REQUEST` error response.
    """

    def __init__(self, method: str):
        super().__init__(
            code=INVALID_REQUEST,
            message=(
                f"Cannot send {method!r}: this transport context has no back-channel for server-initiated requests."
            ),
        )
        self.method = method


class UrlElicitationRequiredError(MCPError):
    """Specialized error for when a tool requires URL mode elicitation(s) before proceeding.

    Servers can raise this error from tool handlers to indicate that the client
    must complete one or more URL elicitations before the request can be processed.

    Example:
        ```python
        raise UrlElicitationRequiredError([
            ElicitRequestURLParams(
                message="Authorization required for your files",
                url="https://example.com/oauth/authorize",
                elicitation_id="auth-001"
            )
        ])
        ```
    """

    def __init__(self, elicitations: list[ElicitRequestURLParams], message: str | None = None):
        """Initialize UrlElicitationRequiredError."""
        if message is None:
            message = f"URL elicitation{'s' if len(elicitations) > 1 else ''} required"

        self._elicitations = elicitations

        super().__init__(
            code=URL_ELICITATION_REQUIRED,
            message=message,
            data={"elicitations": [e.model_dump(by_alias=True, exclude_none=True) for e in elicitations]},
        )

    @property
    def elicitations(self) -> list[ElicitRequestURLParams]:
        """The list of URL elicitations required before the request can proceed."""
        return self._elicitations

    @classmethod
    def from_error(cls, error: ErrorData) -> UrlElicitationRequiredError:
        """Reconstruct from an ErrorData received over the wire."""
        if error.code != URL_ELICITATION_REQUIRED:
            raise ValueError(f"Expected error code {URL_ELICITATION_REQUIRED}, got {error.code}")

        data = cast(dict[str, Any], error.data or {})
        raw_elicitations = cast(list[dict[str, Any]], data.get("elicitations", []))
        elicitations = [ElicitRequestURLParams.model_validate(e) for e in raw_elicitations]
        return cls(elicitations, error.message)
