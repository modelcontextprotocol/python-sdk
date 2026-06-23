# apps

MCP Apps: a tool result carries a `_meta.ui` reference to a `ui://` resource
that the host renders as an interactive surface. The story will register a
`@ui` resource and return it from a tool.

**Status: not yet implemented** ([#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896)).
The `extensions` capability map is not yet surfaced on `MCPServer`, so a server
cannot advertise Apps support and a client cannot negotiate it.

## Spec

[MCP Apps — extensions](https://modelcontextprotocol.io/specification/draft/extensions/apps)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)
