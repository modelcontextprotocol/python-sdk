"""Linear MRTR — keep ``await ctx.elicit()`` genuinely linear (Option H).

The Option B footgun was: ``await elicit()`` *looks* like a suspension point
but is actually a re-entry point, so everything above it runs twice. This
module fixes that by making it a *real* suspension point — the coroutine
frame is held in memory across MRTR rounds, keyed by ``request_state``.

Handler code stays exactly as it was in the SSE era::

    async def my_tool(ctx: LinearCtx, location: str) -> str:
        audit_log(location)        # runs exactly once
        units = await ctx.elicit("Which units?", UnitsSchema)
        audit_log("got units")     # runs exactly once
        return f"{location}: 22°{units.u}"

The wrapper ``linear_mrtr(my_tool)`` translates this into a standard MRTR
``on_call_tool`` handler. Round 1 starts the coroutine; ``elicit()`` sends
an ``IncompleteResult`` back through the wrapper and parks on a stream.
Round 2's retry wakes it with the answer. The coroutine continues from
where it stopped — no re-entry, no double-execution.

**Trade-off**: the server holds the frame in memory between rounds. The
client still sees pure MRTR (no SSE, independent HTTP requests), but the
server is stateful *within* a single tool call. Horizontally-scaled
deployments need sticky routing on the ``request_state`` token, or a
distributed continuation store. Same operational shape as Option A's SSE
hold, just without the long-lived connection.

**When to use this**: migrating existing SSE-era tools to MRTR wire
protocol without rewriting the handler. Or when the linear style is
genuinely clearer than guard-first (complex branching, many rounds).

**When not to**: if you need true statelessness across server instances.
Use Option E/F/G instead — they encode everything the server needs in
``request_state`` itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, TypeVar

import anyio
import anyio.abc
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import BaseModel

from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    IncompleteResult,
    InputRequests,
    TextContent,
)

__all__ = ["LinearCtx", "linear_mrtr", "ContinuationStore"]

T = TypeVar("T", bound=BaseModel)


# ─── Continuation plumbing ───────────────────────────────────────────────────


@dataclass
class _Continuation:
    """In-memory state for one suspended linear handler."""

    ask_send: MemoryObjectSendStream[IncompleteResult | CallToolResult]
    ask_recv: MemoryObjectReceiveStream[IncompleteResult | CallToolResult]
    answer_send: MemoryObjectSendStream[dict[str, Any]]
    answer_recv: MemoryObjectReceiveStream[dict[str, Any]]

    @classmethod
    def new(cls) -> _Continuation:
        ask_s, ask_r = anyio.create_memory_object_stream[IncompleteResult | CallToolResult](1)
        ans_s, ans_r = anyio.create_memory_object_stream[dict[str, Any]](1)
        return cls(ask_send=ask_s, ask_recv=ask_r, answer_send=ans_s, answer_recv=ans_r)

    def close(self) -> None:
        self.ask_send.close()
        self.ask_recv.close()
        self.answer_send.close()
        self.answer_recv.close()


class ContinuationStore:
    """Owns the background task group and the token → continuation map.

    One per server (or per-process). Must be entered as an async context
    manager so the task group is live before any handler runs::

        store = ContinuationStore()
        handler = linear_mrtr(my_tool, store=store)
        server = Server("demo", on_call_tool=handler)

        async with store:
            await server.run(...)

    Continuations expire after ``ttl_seconds`` of inactivity — if the client
    never retries, the frame is reclaimed. Default 5 minutes.
    """

    def __init__(self, *, ttl_seconds: float = 300.0) -> None:
        self._frames: dict[str, _Continuation] = {}
        self._ttl = ttl_seconds
        self._tg: anyio.abc.TaskGroup | None = None

    async def __aenter__(self) -> ContinuationStore:
        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._tg is not None:  # pragma: no branch
            self._tg.cancel_scope.cancel()
            await self._tg.__aexit__(exc_type, exc_val, exc_tb)
            self._tg = None
        self._frames.clear()

    def _check_entered(self) -> None:
        if self._tg is None:
            raise RuntimeError("ContinuationStore not entered — use `async with store:` around server.run()")

    def _start(self, token: str, cont: _Continuation, runner: Callable[[], Awaitable[None]]) -> None:
        assert self._tg is not None
        self._frames[token] = cont

        async def _run_and_cleanup() -> None:
            try:
                with anyio.move_on_after(self._ttl):
                    await runner()
            finally:
                cont.close()
                self._frames.pop(token, None)

        self._tg.start_soon(_run_and_cleanup)

    def get(self, token: str) -> _Continuation | None:
        return self._frames.get(token)


# ─── The linear context ──────────────────────────────────────────────────────


class LinearCtx:
    """The ``ctx`` handed to a linear handler. ``await ctx.elicit()`` genuinely suspends."""

    def __init__(self, continuation: _Continuation) -> None:
        self._cont = continuation
        self._counter = 0

    async def elicit(self, message: str, schema: type[T]) -> T:
        """Ask the client a question. Suspends until the answer arrives on a later round.

        The schema is a Pydantic model; the elicitation requestedSchema is
        derived from it, and the answer is validated back into an instance.

        Raises:
            ElicitDeclined: if the user declined or cancelled.
        """
        key = f"q{self._counter}"
        self._counter += 1
        responses = await self.ask(
            {
                key: ElicitRequest(
                    params=ElicitRequestFormParams(message=message, requested_schema=schema.model_json_schema())
                )
            }
        )
        answer = responses.get(key, {})
        if answer.get("action") != "accept":
            raise ElicitDeclined(answer.get("action", "cancel"))
        return schema.model_validate(answer.get("content", {}))

    async def ask(self, input_requests: InputRequests) -> dict[str, Any]:
        """Send one or more input requests in a single round; returns the full responses dict.

        Lower-level than :meth:`elicit` — hand-rolled schemas, no validation,
        multiple asks batched into one round.
        """
        await self._cont.ask_send.send(IncompleteResult(input_requests=input_requests))
        return await self._cont.answer_recv.receive()


class ElicitDeclined(Exception):
    """Raised inside a linear handler when the user declines or cancels an elicitation."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f"Elicitation {action}")


# ─── The wrapper ─────────────────────────────────────────────────────────────


LinearHandler = Callable[[LinearCtx, dict[str, Any]], Awaitable[CallToolResult | str]]
"""Signature of a linear handler: ``(ctx, arguments) -> CallToolResult | str``."""


class _LinearMrtrWrapper:
    def __init__(self, handler: LinearHandler, store: ContinuationStore) -> None:
        self._handler = handler
        self._store = store

    async def __call__(self, ctx: Any, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
        token = params.request_state

        if token is None:
            return await self._start(params)
        return await self._resume(token, params)

    async def _start(self, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
        self._store._check_entered()  # pyright: ignore[reportPrivateUsage]
        token = uuid.uuid4().hex
        cont = _Continuation.new()
        linear_ctx = LinearCtx(cont)
        args = dict(params.arguments or {})

        async def runner() -> None:
            try:
                result = await self._handler(linear_ctx, args)
                if isinstance(result, str):
                    result = CallToolResult(content=[TextContent(text=result)])
                await cont.ask_send.send(result)
            except ElicitDeclined as exc:
                await cont.ask_send.send(
                    CallToolResult(content=[TextContent(text=f"Cancelled ({exc.action}).")], is_error=False)
                )
            except Exception as exc:  # noqa: BLE001
                await cont.ask_send.send(CallToolResult(content=[TextContent(text=str(exc))], is_error=True))

        self._store._start(token, cont, runner)  # pyright: ignore[reportPrivateUsage]
        return await self._next(token, cont)

    async def _resume(self, token: str, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
        cont = self._store.get(token)
        if cont is None:
            return CallToolResult(
                content=[TextContent(text="Continuation expired or unknown. Retry the tool call from scratch.")],
                is_error=True,
            )
        await cont.answer_send.send(params.input_responses or {})
        return await self._next(token, cont)

    async def _next(self, token: str, cont: _Continuation) -> CallToolResult | IncompleteResult:
        msg = await cont.ask_recv.receive()
        if isinstance(msg, IncompleteResult):
            return IncompleteResult(input_requests=msg.input_requests, request_state=token)
        return msg


def linear_mrtr(handler: LinearHandler, *, store: ContinuationStore) -> _LinearMrtrWrapper:
    """Wrap a linear ``await ctx.elicit()``-style handler into an MRTR ``on_call_tool``.

    The handler runs exactly once, front to back. ``ctx.elicit()`` is a real
    suspension point — the coroutine frame is held in ``store`` between MRTR
    rounds, keyed by ``request_state``.

    Args:
        handler: ``async (ctx: LinearCtx, arguments: dict) -> CallToolResult | str``.
            Returning a ``str`` is shorthand for a single TextContent.
        store: The :class:`ContinuationStore` that owns the background task
            group. Must be entered as an async context manager around the
            server's run loop.
    """
    return _LinearMrtrWrapper(handler, store)
