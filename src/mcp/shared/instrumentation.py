"""Instrumentation interface for MCP SDK observability.

This module provides a pluggable instrumentation interface for monitoring
MCP request/response lifecycle. It's designed to support integration with
OpenTelemetry and other observability tools.
"""

from __future__ import annotations

from typing import Any, Protocol

from mcp.types import RequestId


class Instrumenter(Protocol):
    """Protocol for instrumenting MCP request/response lifecycle.

    Implementers can use this to integrate with OpenTelemetry, custom metrics,
    logging frameworks, or other observability tools.

    All methods are optional (no-op implementations are valid). Exceptions
    raised by instrumentation hooks are logged but do not affect request processing.
    """

    def on_request_start(
        self,
        request_id: RequestId,
        request_type: str,
        method: str | None = None,
        **metadata: Any,
    ) -> None:
        """Called when a request starts processing.

        Args:
            request_id: Unique identifier for this request
            request_type: Type name of the request (e.g., "CallToolRequest")
            method: Optional method name being called (e.g., tool/resource name)
            **metadata: Additional context (session_type, client_info, etc.)
        """
        ...

    def on_request_end(
        self,
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        """Called when a request completes (successfully or not).

        Args:
            request_id: Unique identifier for this request
            request_type: Type name of the request
            success: Whether the request completed successfully
            duration_seconds: Optional request duration in seconds
            **metadata: Additional context (error info, result summary, etc.)
        """
        ...

    def on_error(
        self,
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata: Any,
    ) -> None:
        """Called when an error occurs during request processing.

        Args:
            request_id: Request ID if available, None for session-level errors
            error: The exception that occurred
            error_type: Type name of the error
            **metadata: Additional error context
        """
        ...


class NoOpInstrumenter:
    """Default no-op implementation of the Instrumenter protocol.

    This implementation does nothing and has minimal overhead.
    Used as the default when no instrumentation is configured.
    """

    def on_request_start(
        self,
        request_id: RequestId,
        request_type: str,
        method: str | None = None,
        **metadata: Any,
    ) -> None:
        """No-op implementation."""
        pass

    def on_request_end(
        self,
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        """No-op implementation."""
        pass

    def on_error(
        self,
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata: Any,
    ) -> None:
        """No-op implementation."""
        pass


# Global default instance
_default_instrumenter = NoOpInstrumenter()


def get_default_instrumenter() -> Instrumenter:
    """Get the default no-op instrumenter instance."""
    return _default_instrumenter
