# skills

SEP-2640 skills: a server exposes a `skill://index.json` directory resource and
`@skill` / `@skillDir` registrations that a host can read to bootstrap
agent-level instructions. The story will list skills and read one.

**Status: not yet implemented** ([#2896](https://github.com/modelcontextprotocol/python-sdk/issues/2896)).
The `extensions` capability map is not yet surfaced on `MCPServer`, so a server
cannot advertise the skills extension.

## Spec

[SEP-2640 — skills](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2640)
· [SEP-2133 — extensions capability](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2133)
