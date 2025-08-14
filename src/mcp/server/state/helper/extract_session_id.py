from __future__ import annotations
from typing import Optional

from mcp.server.fastmcp import Context
from mcp.server.lowlevel.server import LifespanResultT, ServerSession

def extract_session_id(ctx: Context[ServerSession, LifespanResultT]) -> Optional[str]:
    """Extract session id from the current request context (headers or query).

    Tries headers 'x-session-id' / 'x-state-id', then query params 'session_id' / 'state_id'.
    Returns None when no request context is available or no id is present.
    """
    try:
        req = ctx.request_context.request
    except Exception:
        return None

    # Try headers first
    try:
        h = getattr(req, "headers", None)
        if h:
            v = h.get("x-session-id") or h.get("x-state-id")
            if isinstance(v, str) and v:
                return v
    except Exception:
        pass

    # Fallback to query params
    try:
        q = getattr(req, "query", None) or getattr(req, "query_params", None)
        if q:
            v = q.get("session_id") or q.get("state_id")
            if isinstance(v, str) and v:
                return v
    except Exception:
        pass

    return None
