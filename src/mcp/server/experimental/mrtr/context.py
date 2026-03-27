"""MrtrCtx — idempotency guard for side-effects (Option F)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.experimental.mrtr._state import decode_state, encode_state
from mcp.types import CallToolRequestParams, IncompleteResult, InputRequests


class MrtrCtx:
    """MRTR context with a ``once`` guard tracked in ``request_state``.

    Handler stays monolithic (guard-first, like a raw MRTR handler), but
    side-effects can be wrapped for at-most-once execution across retries::

        ctx = MrtrCtx(params)
        ctx.once("audit", lambda: audit_log(params.arguments["x"]))

        units = input_response(params, "units")
        if units is None:
            return ctx.incomplete({"units": ElicitRequest(...)})

        return CallToolResult(...)

    Opt-in: an unwrapped mutation still fires twice. The footgun isn't
    eliminated — it's made visually distinct from safe code, which is
    reviewable. A bare ``db.write()`` above the guard is the red flag;
    ``ctx.once("write", lambda: db.write())`` reads as "I considered
    re-entry."

    Crash window: if the server dies between ``fn()`` completing and
    ``request_state`` reaching the client, the next invocation re-executes.
    At-most-once under normal operation, not crash-safe. For financial
    operations use external idempotency (request ID as DB unique key).
    """

    def __init__(self, params: CallToolRequestParams) -> None:
        self._params = params
        prior = decode_state(params.request_state)
        self._executed: set[str] = set(prior.get("executed", []))

    @property
    def input_responses(self) -> dict[str, Any] | None:  # pragma: no cover
        return self._params.input_responses

    def once(self, key: str, fn: Callable[[], Any]) -> None:
        """Run ``fn`` at most once across all MRTR rounds for this tool call.

        On subsequent rounds where ``key`` is marked executed in
        ``request_state``, ``fn`` is skipped entirely.
        """
        if key in self._executed:
            return
        fn()
        self._executed.add(key)

    def has_run(self, key: str) -> bool:
        """Check if ``once(key, ...)`` has fired on a prior round."""
        return key in self._executed

    def incomplete(self, input_requests: InputRequests) -> IncompleteResult:
        """Build an IncompleteResult that carries the executed-keys set.

        Call this instead of constructing ``IncompleteResult`` directly so
        the ``once`` guard holds across retry. Without this, ``once`` is a
        no-op on the next round.
        """
        return IncompleteResult(
            input_requests=input_requests,
            request_state=encode_state({"executed": sorted(self._executed)}),
        )
