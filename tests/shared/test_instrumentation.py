"""Tests for instrumentation interface."""

from typing import Any

import pytest

from mcp.shared.instrumentation import NoOpInstrumenter, get_default_instrumenter
from mcp.types import RequestId


class MockInstrumenter:
    """Track calls to instrumentation hooks for testing."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def on_request_start(
        self, request_id: RequestId, request_type: str, method: str | None = None, **metadata: Any
    ) -> dict[str, Any]:
        call: dict[str, Any] = {
            "hook": "on_request_start",
            "request_id": request_id,
            "request_type": request_type,
            "method": method,
            "metadata": metadata,
        }
        self.calls.append(call)
        # Return the call itself as a token for testing
        return call

    def on_request_end(
        self,
        token: Any,
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        self.calls.append(
            {
                "hook": "on_request_end",
                "token": token,
                "request_id": request_id,
                "request_type": request_type,
                "success": success,
                "duration_seconds": duration_seconds,
                "metadata": metadata,
            }
        )

    def on_error(
        self, token: Any, request_id: RequestId | None, error: Exception, error_type: str, **metadata: Any
    ) -> None:
        self.calls.append(
            {
                "hook": "on_error",
                "token": token,
                "request_id": request_id,
                "error": error,
                "error_type": error_type,
                "metadata": metadata,
            }
        )

    def get_calls_by_hook(self, hook_name: str) -> list[dict[str, Any]]:
        """Get all calls to a specific hook."""
        return [call for call in self.calls if call["hook"] == hook_name]

    def get_calls_by_request_id(self, request_id: RequestId) -> list[dict[str, Any]]:
        """Get all calls for a specific request_id."""
        return [call for call in self.calls if call.get("request_id") == request_id]


@pytest.mark.anyio
async def test_noop_instrumenter():
    """Test that NoOpInstrumenter does nothing and doesn't raise errors."""
    instrumenter = NoOpInstrumenter()

    # Should not raise any errors
    token = instrumenter.on_request_start(request_id=1, request_type="TestRequest")
    instrumenter.on_request_end(token=token, request_id=1, request_type="TestRequest", success=True)
    instrumenter.on_error(token=token, request_id=1, error=Exception("test"), error_type="Exception")


def test_get_default_instrumenter():
    """Test that get_default_instrumenter returns a NoOpInstrumenter."""
    instrumenter = get_default_instrumenter()
    assert isinstance(instrumenter, NoOpInstrumenter)


def test_instrumenter_protocol():
    """Test that MockInstrumenter implements the Instrumenter protocol."""
    instrumenter = MockInstrumenter()

    # Call all methods to ensure they exist
    token = instrumenter.on_request_start(request_id=1, request_type="TestRequest", method="test_method")
    instrumenter.on_request_end(
        token=token, request_id=1, request_type="TestRequest", success=True, duration_seconds=1.5
    )
    instrumenter.on_error(token=token, request_id=1, error=Exception("test"), error_type="Exception")

    # Verify calls were tracked
    assert len(instrumenter.calls) == 3
    assert instrumenter.get_calls_by_hook("on_request_start")[0]["request_type"] == "TestRequest"
    assert instrumenter.get_calls_by_hook("on_request_end")[0]["success"] is True
    assert instrumenter.get_calls_by_hook("on_error")[0]["error_type"] == "Exception"


def test_instrumenter_tracks_request_id():
    """Test that request_id is tracked consistently across hooks."""
    instrumenter = MockInstrumenter()
    test_request_id = 42

    token = instrumenter.on_request_start(request_id=test_request_id, request_type="TestRequest")
    instrumenter.on_request_end(token=token, request_id=test_request_id, request_type="TestRequest", success=True)

    # Verify request_id is consistent
    calls = instrumenter.get_calls_by_request_id(test_request_id)
    assert len(calls) == 2
    assert all(call["request_id"] == test_request_id for call in calls)


def test_instrumenter_metadata():
    """Test that metadata is passed through correctly."""
    instrumenter = MockInstrumenter()

    instrumenter.on_request_start(
        request_id=1, request_type="TestRequest", method="test_tool", session_type="server", custom_field="custom_value"
    )

    call = instrumenter.get_calls_by_hook("on_request_start")[0]
    assert call["metadata"]["session_type"] == "server"
    assert call["metadata"]["custom_field"] == "custom_value"
    assert call["method"] == "test_tool"


def test_instrumenter_duration_tracking():
    """Test that duration is passed to on_request_end."""
    instrumenter = MockInstrumenter()

    token = {"test": "token"}
    instrumenter.on_request_end(
        token=token, request_id=1, request_type="TestRequest", success=True, duration_seconds=2.5
    )

    call = instrumenter.get_calls_by_hook("on_request_end")[0]
    assert call["duration_seconds"] == 2.5
    assert call["token"] == token


def test_instrumenter_error_info():
    """Test that error information is captured correctly."""
    instrumenter = MockInstrumenter()
    test_error = ValueError("test error message")

    token = {"test": "token"}
    instrumenter.on_error(
        token=token, request_id=1, error=test_error, error_type="ValueError", extra_info="additional context"
    )

    call = instrumenter.get_calls_by_hook("on_error")[0]
    assert call["error"] is test_error
    assert call["error_type"] == "ValueError"
    assert call["metadata"]["extra_info"] == "additional context"
    assert call["token"] == token


def test_instrumenter_token_flow():
    """Test that token is passed correctly from start to end/error."""
    instrumenter = MockInstrumenter()

    # Start request and get token
    token = instrumenter.on_request_start(request_id=1, request_type="TestRequest", method="test_tool")
    assert token is not None
    assert isinstance(token, dict)
    assert token["request_id"] == 1

    # End request with the token
    instrumenter.on_request_end(
        token=token, request_id=1, request_type="TestRequest", success=True, duration_seconds=1.5
    )

    # Verify token is the same
    start_call = instrumenter.get_calls_by_hook("on_request_start")[0]
    end_call = instrumenter.get_calls_by_hook("on_request_end")[0]
    assert end_call["token"] is start_call  # Token should be the start call itself

    # Test error path
    token2 = instrumenter.on_request_start(request_id=2, request_type="TestRequest2")
    instrumenter.on_error(token=token2, request_id=2, error=Exception("test"), error_type="Exception")

    error_call = instrumenter.get_calls_by_hook("on_error")[0]
    assert error_call["token"]["request_id"] == 2
