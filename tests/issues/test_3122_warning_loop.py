"""Regression test for #3122.

``Server._handle_message`` used to log recorded warnings while still inside the
``warnings.catch_warnings(record=True)`` block. Because ``record=True`` forces
an "always" filter, a warning emitted by a logging handler during that logging
step was appended to the very list being iterated, so the loop never
terminated. The loop is synchronous, so task cancellation could not interrupt
it.

The fix snapshots the recorded warnings and logs them after leaving the
``catch_warnings`` block, so handler-emitted warnings can no longer extend the
iteration. This test drives ``_handle_message`` with a request that records one
warning and a logging handler that itself warns on every record; the handler
must be invoked exactly once. The handler stops re-warning after a cap so that
the pre-fix infinite loop terminates and fails the assertion instead of hanging
the test session.
"""

import logging
import warnings
from unittest.mock import AsyncMock, Mock

import pytest

import mcp.types as types
from mcp.server.lowlevel.server import Server
from mcp.server.session import ServerSession
from mcp.shared.session import RequestResponder


class _WarningEmittingHandler(logging.Handler):
    """A logging handler whose emit() raises a warning, mimicking e.g. a
    timestamp formatter that calls a deprecated API on every record. It stops
    after ``cap`` records so a regressed (looping) build still terminates."""

    def __init__(self, cap: int = 100) -> None:
        super().__init__()
        self.emit_count = 0
        self._cap = cap

    def emit(self, record: logging.LogRecord) -> None:
        self.emit_count += 1
        if self.emit_count <= self._cap:
            warnings.warn("warning raised while logging", stacklevel=1)


@pytest.mark.anyio
async def test_handle_message_logs_each_warning_once_when_handler_warns():
    server = Server("test-server")

    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock()

    async def _handle_request_that_warns(*args: object, **kwargs: object) -> None:
        warnings.warn("warning raised while handling the request", stacklevel=1)

    server._handle_request = _handle_request_that_warns  # type: ignore[assignment]

    responder = Mock(spec=RequestResponder)
    responder.request = types.ClientRequest(root=types.PingRequest(method="ping"))
    responder.__enter__ = Mock(return_value=responder)
    responder.__exit__ = Mock(return_value=None)

    server_logger = logging.getLogger("mcp.server.lowlevel.server")
    handler = _WarningEmittingHandler()
    server_logger.addHandler(handler)
    previous_level = server_logger.level
    server_logger.setLevel(logging.INFO)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            await server._handle_message(responder, session, {}, raise_exceptions=False)
    finally:
        server_logger.removeHandler(handler)
        server_logger.setLevel(previous_level)

    assert handler.emit_count == 1
