"""Workarounds for CPython interpreter bugs the SDK papers over."""

import anyio.lowlevel

__all__ = ["resync_tracer"]


async def resync_tracer() -> None:
    """Resync coverage tracing after a cancelled task-group join.

    A cancel delivered at a join resumes the awaiting coroutine chain via
    `coro.throw()`; on CPython 3.11 (python/cpython#106749) that drops the
    `'call'` trace events for the outer frames and desyncs coverage's CTracer
    until the chain next suspends and resumes normally. Yielding once here
    resumes via `.send()`, which re-stamps the missing events. Shielded so a
    pending outer cancel is not re-delivered at this point; behaviorally a
    no-op. Delete this module when Python 3.11 support ends (EOL 2027-10).
    """
    await anyio.lowlevel.cancel_shielded_checkpoint()
