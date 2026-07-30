"""Prewarm the SDK's deferred startup work in a host's startup hook.

Imports stay fast because the heavy pieces load on first use: a protocol
version's wire schemas load on the first message parsed for that version, and
each pydantic model builds its validator the first time it is used. A host that
would rather pay that once, before serving traffic, calls `mcp.warm()`.
"""

import mcp

# Build the deferred validators now: the version-independent set, plus the
# routing surface of each protocol version this host will serve.
report = mcp.warm("2025-11-25")
print(f"prewarmed {report.models} models and {report.adapters} adapters in {report.elapsed_ms} ms")
