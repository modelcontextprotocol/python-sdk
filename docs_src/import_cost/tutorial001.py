"""Prewarm the SDK's deferred startup work.

Imports stay fast because the heavy pieces load on first use: a protocol
version's wire schemas load on the first message parsed for that version, and
each pydantic model builds its validator the first time it is used. A host that
would rather pay all of that once, before serving traffic, can trigger it here.
"""

import mcp_types
from mcp_types.methods import CLIENT_REQUESTS

# Load the wire-schema package for each protocol version you will speak.
# Reading any row of a surface map imports that version's package.
_ = CLIENT_REQUESTS[("initialize", "2025-11-25")]

# Build the validators for the models on your hot path up front.
for model in (mcp_types.CallToolRequest, mcp_types.CallToolResult, mcp_types.Tool):
    model.model_rebuild()
