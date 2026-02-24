from __future__ import annotations

from builtins import BaseExceptionGroup
from typing import Any, cast

from mcp.types import URL_ELICITATION_REQUIRED, ElicitRequestURLParams, ErrorData, JSONRPCError


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


class StatelessModeNotSupported(RuntimeError):
    """Raised when attempting to use a method that is not supported in stateless mode.

    Server-to-client requests (sampling, elicitation, list_roots) are not
    supported in stateless HTTP mode because there is no persistent connection
    for bidirectional communication.
    """

    def __init__(self, method: str):
        super().__init__(
            f"Cannot use {method} in stateless HTTP mode. "
            "Stateless mode does not support server-to-client requests. "
            "Use stateful mode (stateless_http=False) to enable this feature."
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


def unwrap_task_group_exception(exc: BaseException) -> BaseException:
    """Unwrap an exception from a task group, extracting only the real error.

    When anyio task groups fail, they raise BaseExceptionGroup containing:
    - The original error that caused the failure
    - CancelledError from sibling tasks that were cancelled

    This function extracts only the real error, ignoring cancelled siblings.

    Args:
        exc: The exception to unwrap (could be any exception)

    Returns:
        The unwrapped exception if it was an ExceptionGroup with a real error,
        otherwise the original exception

    Example:
        ```python
        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(task1)
                tg.start_soon(task2)
        except BaseExceptionGroup as e:
            # Extract only the real error, ignore CancelledError
            real_exc = unwrap_task_group_exception(e)
            raise real_exc
        ```
    """
    import anyio

    # If not an exception group, return as-is
    if not isinstance(exc, BaseExceptionGroup):
        return exc

    # Find the first non-cancelled exception
    cancelled_exc_class = anyio.get_cancelled_exc_class()
    for sub_exc in exc.exceptions:
        if not isinstance(sub_exc, cancelled_exc_class):
            # Type narrowing: we know this is not a CancelledError
            return sub_exc  # type: ignore[reportUnknownVariableType]

    # All were cancelled, return the group
    return exc  # type: ignore[reportUnknownVariableType]
