"""Regression test for #3122.

``Server._handle_message`` used to log recorded warnings while still inside the
``warnings.catch_warnings(record=True)`` block. Because ``record=True`` forces
an "always" filter, a warning emitted by a logging handler during that logging
step was appended to the very list being iterated, so the loop never
terminated. The loop is synchronous, so task cancellation could not interrupt
it.

The fix snapshots the recorded warnings and logs them after leaving the
``catch_warnings`` block, so handler-emitted warnings can no longer extend the
iteration.

The test records two warnings during handling and attaches a logging handler
that itself warns on the first record only. After the fix each recorded warning
is logged exactly once, so the handler is invoked twice (once per recorded
warning) and no extra records appear. Before the fix, the handler's warning fed
back into the iterated list and the handler was invoked a third time. Warning
on only the first record keeps the handler from feeding the loop unboundedly, so
a regressed build terminates and fails the assertion instead of hanging.
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
    """A logging handler whose emit() raises a warning for the first ``cap``
    records, mimicking e.g. a timestamp formatter that warns per record."""

    def __init__(self, cap: int = 1) -> None:
        super().__init__()
        self.emit_count = 0
        self._cap = cap

    def emit(self, record: logging.LogRecord) -> None:
        self.emit_count += 1
        if self.emit_count <= self._cap:
            warnings.warn("warning raised while logging", stacklevel=1)


@pytest.mark.anyio
async def test_handle_message_logs_each_recorded_warning_once() -> None:
    server = Server("test-server")

    session = Mock(spec=ServerSession)
    session.send_log_message = AsyncMock()

    async def _handle_request_that_warns(*args: object, **kwargs: object) -> None:
        warnings.warn("first warning raised while handling the request", stacklevel=1)
        warnings.warn("second warning raised while handling the request", stacklevel=1)

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

    # Two warnings were recorded during handling, so the handler is invoked
    # exactly twice. A regressed build re-appends the handler's own warning and
    # invokes it a third time.
    assert handler.emit_count == 2
