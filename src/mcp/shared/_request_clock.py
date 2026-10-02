"""A request's timeout measures the peer, so its clock stops while the request waits on a person.

The clock travels in a `ContextVar`: the HTTP transports run each outgoing message in its sender's
context, which is how code far below `send_raw_request` finds the clock of the request it serves.

Nothing in this module is public API: it may change or be removed without notice. It is likely to
change with the client dispatcher work in https://github.com/modelcontextprotocol/python-sdk/pull/3517.
"""

import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import anyio


class RequestClock:
    """One request's timeout, as a budget of seconds that is spent only while the clock runs.

    Not public API: may change or be removed without notice.
    """

    def __init__(self, timeout: float | None, scope: anyio.CancelScope) -> None:
        self._budget = math.inf if timeout is None else timeout
        self._scope = scope
        self._pauses = 1  # the write, which is off the clock too; `start()` ends it

    def start(self) -> None:
        self.resume()

    def pause(self) -> None:
        if not self._pauses:
            self._budget = self._scope.deadline - anyio.current_time()
            self._scope.deadline = math.inf
        self._pauses += 1

    def resume(self) -> None:
        self._pauses -= 1
        if not self._pauses:
            self._scope.deadline = anyio.current_time() + self._budget


_clock: ContextVar[RequestClock | None] = ContextVar("request_clock", default=None)


@contextmanager
def request_clock(timeout: float | None) -> Iterator[RequestClock]:
    """Put a clock, not yet started, in the context of the request sent in this block.

    Raises `TimeoutError` once the clock has run for `timeout` seconds.

    Not public API: may change or be removed without notice.
    """
    with anyio.CancelScope() as scope:
        clock = RequestClock(timeout, scope)
        token = _clock.set(clock)
        try:
            yield clock
        finally:
            _clock.reset(token)
    # Not `fail_after`: it re-reads the deadline here, which a pause may have moved since it expired.
    if scope.cancelled_caught:
        raise TimeoutError


@contextmanager
def waiting_on_a_person() -> Iterator[None]:
    """Stop the clock of the request this code is serving while the block is open; a no-op if there is none.

    Not public API: may change or be removed without notice.
    """
    clock = _clock.get()
    if clock is None:
        yield
        return
    clock.pause()
    try:
        yield
    finally:
        clock.resume()
