"""MRTR (SEP-2322) server-side primitives — footgun-prevention layers.

!!! warning
    These APIs are experimental and may change or be removed without notice.

The naive MRTR handler is de-facto GOTO: re-entry jumps to the top, state
progression is implicit in ``input_responses`` checks, and side-effects
above the guard execute on every retry. Two primitives here make safe code
the easy path:

- :class:`MrtrCtx` — ``ctx.once(key, fn)`` idempotency guard. Opt-in per
  call site; unwrapped mutations still fire twice. Makes the hazard
  *visually distinct* from safe code, which is reviewable. Lightweight —
  use for single-question tools with one side-effect.

- :class:`ToolBuilder` — structural decomposition into named steps.
  ``end_step`` runs exactly once, structurally unreachable until every
  ``incomplete_step`` has returned data. No "above the guard" zone to get
  wrong. Boilerplate pays for itself at 3+ rounds.

Both track progress in ``request_state`` (base64-JSON here; a production
SDK MUST HMAC-sign the blob — see :mod:`._state`).

The :mod:`.compat` module holds the dual-path shims (Options A and D from
the comparison deck). They're comparison artifacts, not ship targets —
Option E (degrade-only) is the SDK default and requires neither.
"""

from mcp.server.experimental.mrtr._state import decode_state, encode_state, input_response
from mcp.server.experimental.mrtr.builder import EndStep, IncompleteStep, ToolBuilder
from mcp.server.experimental.mrtr.compat import MrtrHandler, dispatch_by_version, sse_retry_shim
from mcp.server.experimental.mrtr.context import MrtrCtx
from mcp.server.experimental.mrtr.linear import ContinuationStore, ElicitDeclined, LinearCtx, linear_mrtr

__all__ = [
    "MrtrCtx",
    "ToolBuilder",
    "IncompleteStep",
    "EndStep",
    "MrtrHandler",
    "LinearCtx",
    "ContinuationStore",
    "ElicitDeclined",
    "linear_mrtr",
    "input_response",
    "encode_state",
    "decode_state",
    "sse_retry_shim",
    "dispatch_by_version",
]
