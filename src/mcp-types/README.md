# MCP Types

The wire types for the [Model Context Protocol](https://modelcontextprotocol.io).

This package holds the protocol message models, JSON-RPC envelope types, per-version
surface validators, and the protocol-version registry. Its only runtime dependencies are
`pydantic` and `typing-extensions`, so it can be installed on its own when you need to
(de)serialize MCP traffic without pulling in the full `mcp` SDK.

```python
from mcp_types import Tool, CallToolRequest
from mcp_types.version import LATEST_PROTOCOL_VERSION
```

The `mcp` package re-exports these names, so existing `from mcp import Tool` imports
keep working.
