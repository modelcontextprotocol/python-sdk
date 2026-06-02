# mcp-types

Type definitions for the [Model Context Protocol](https://modelcontextprotocol.io).

This package contains the Pydantic models and JSON-RPC types that describe the MCP wire
protocol. It is a dependency of the [`mcp`](https://pypi.org/project/mcp/) SDK and can be
used on its own when you only need the protocol types without the client/server runtime.

```python
from mcp_types import Tool, CallToolRequest
```
