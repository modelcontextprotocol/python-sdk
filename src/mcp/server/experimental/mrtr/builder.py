"""ToolBuilder — structural step decomposition (Option G)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar

from mcp.server.experimental.mrtr._state import decode_state, encode_state
from mcp.types import CallToolRequestParams, CallToolResult, IncompleteResult

ArgsT = TypeVar("ArgsT")


IncompleteStep = Callable[[ArgsT, dict[str, Any]], IncompleteResult | dict[str, Any]]
"""An incomplete-step function. Receives args + all input responses collected
so far. Returns either an :class:`IncompleteResult` (needs more input) or a
dict to merge into the collected data passed to the next step.

MUST be idempotent — it can re-run if the client tampers with ``request_state``
(unsigned in this draft) or if a step before it wasn't the most-recently
completed. Side-effects belong in the end step.
"""

EndStep = Callable[[ArgsT, dict[str, Any]], CallToolResult]
"""The end-step function. Receives args + the merged data from all prior
steps. Runs exactly once, when every incomplete step has returned data.
This is the safe zone — put side-effects here.
"""


class ToolBuilder(Generic[ArgsT]):
    """Explicit step decomposition for MRTR handlers.

    The monolithic handler becomes a sequence of named step functions.
    ``end_step`` is structurally unreachable until every ``incomplete_step``
    has returned data — the SDK's step-tracking (via ``request_state``) is
    the guard, not developer discipline::

        def ask_units(args, inputs):
            u = inputs.get("units")
            if not u or u.get("action") != "accept":
                return IncompleteResult(input_requests={"units": ElicitRequest(...)})
            return {"units": u["content"]["u"]}

        def fetch_weather(args, collected):
            audit_log(args)              # runs exactly once
            return CallToolResult(...)   # uses collected["units"]

        handler = (
            ToolBuilder[dict[str, str]]()
            .incomplete_step("ask_units", ask_units)
            .end_step(fetch_weather)
            .build()
        )

        server = Server("demo", on_call_tool=handler)

    Steps are named (not ordinal) so reordering during development doesn't
    silently remap data. Each name must be unique; ``build()`` raises on
    duplicates.

    Boilerplate vs a raw guard-first handler: two function defs + ``.build()``
    to replace a 3-line ``if not x: return IncompleteResult(...)``. Worth it at
    3+ rounds or when the side-effect story matters. Overkill for a single
    question — use :class:`mcp.server.experimental.mrtr.MrtrCtx` instead.
    """

    def __init__(self) -> None:
        self._steps: list[tuple[str, IncompleteStep[ArgsT]]] = []
        self._end: EndStep[ArgsT] | None = None

    def incomplete_step(self, name: str, fn: IncompleteStep[ArgsT]) -> ToolBuilder[ArgsT]:
        """Append a step that may return IncompleteResult or data to collect."""
        self._steps.append((name, fn))
        return self

    def end_step(self, fn: EndStep[ArgsT]) -> ToolBuilder[ArgsT]:
        """Set the final step that runs exactly once with all collected data."""
        self._end = fn
        return self

    def build(self) -> Callable[[Any, CallToolRequestParams], Awaitable[CallToolResult | IncompleteResult]]:
        """Produce a lowlevel ``on_call_tool`` handler."""
        if self._end is None:
            raise ValueError("ToolBuilder: end_step is required")
        names = [n for n, _ in self._steps]
        if len(names) != len(set(names)):
            raise ValueError(f"ToolBuilder: duplicate step names in {names}")

        steps = list(self._steps)
        end = self._end

        async def handler(ctx: Any, params: CallToolRequestParams) -> CallToolResult | IncompleteResult:
            args: ArgsT = params.arguments  # type: ignore[assignment]
            prior = decode_state(params.request_state)
            done: set[str] = set(prior.get("done", []))
            inputs = params.input_responses or {}
            collected: dict[str, Any] = dict(prior.get("collected", {}))

            for name, step in steps:
                if name in done:
                    continue
                result = step(args, inputs)
                if isinstance(result, IncompleteResult):
                    return IncompleteResult(
                        input_requests=result.input_requests,
                        request_state=encode_state({"done": sorted(done), "collected": collected}),
                    )
                collected.update(result)
                done.add(name)

            return end(args, collected)

        return handler
