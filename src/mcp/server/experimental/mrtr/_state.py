"""request_state encode/decode and input_responses sugar.

!!! warning "Unsigned — advisory only"
    Plain base64-JSON. A production SDK MUST HMAC-sign the blob because the
    client can otherwise forge step-done / once-executed markers and skip the
    guards entirely. A per-session key derived from the initialize handshake
    keeps it stateless. Without signing, the safety story of MrtrCtx /
    ToolBuilder is advisory, not enforced.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

from mcp.types import CallToolRequestParams


def encode_state(state: Any) -> str:
    """Encode a JSON-serializable value into an opaque request_state string."""
    return base64.b64encode(json.dumps(state).encode()).decode()


def decode_state(blob: str | None) -> dict[str, Any]:
    """Decode a request_state string. Returns {} on None/empty/malformed."""
    if not blob:
        return {}
    try:
        result = json.loads(base64.b64decode(blob))
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}
    except (ValueError, json.JSONDecodeError):  # pragma: no cover
        return {}


def input_response(params: CallToolRequestParams, key: str) -> dict[str, Any] | None:
    """Pull an accepted elicitation's content out of ``params.input_responses``.

    Returns ``None`` if the key is absent, declined, or cancelled. Sugar for
    the common guard-first pattern::

        units = input_response(params, "units")
        if units is None:
            return IncompleteResult(input_requests={"units": ...})
    """
    if not params.input_responses:
        return None
    entry = params.input_responses.get(key)
    if not entry:
        return None
    if entry.get("action") != "accept":
        return None
    return entry.get("content")
