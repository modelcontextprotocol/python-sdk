# mcp-codemod

Automated rewrites for migrating code between major versions of the
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

```bash
uvx mcp-codemod v1-to-v2 ./src
```

It rewrites every change whose meaning is unambiguous from the file alone, and
inserts a `# mcp-codemod:` comment above every site it recognized but would not
guess at. After a run, this is the complete list of what is left for a human:

```bash
grep -rn '# mcp-codemod:' ./src
```

Run it on a clean branch, read the diff, and follow the markers into the
[migration guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md).
Re-running on its own output is a no-op, so it is safe to apply again after a
manual fix-up.

## What it rewrites

- Import paths that moved (`mcp.server.fastmcp` -> `mcp.server.mcpserver`,
  `mcp.types` -> `mcp_types`), including `from mcp import types`.
- Renamed symbols (`FastMCP` -> `MCPServer`, `McpError` -> `MCPError`,
  `streamablehttp_client` -> `streamable_http_client`), resolved through the
  file's imports so an aliased import or an unrelated symbol with the same name
  is never touched.
- `McpError(...)` calls to `MCPError.from_error_data(...)`, which takes the
  same single `ErrorData` argument the v1 constructor did. (`e.error.code` and
  friends are deliberately left alone: they still work on v2.)
- camelCase attribute reads on `mcp.types` models to their snake_case v2
  spellings (`.inputSchema` -> `.input_schema`), restricted to the field names
  the v1 types actually declared. Other camelCase APIs (`logging.getLogger`, a
  receiver that resolves to another package) are never considered, and a name
  that one of your own classes declares (`inputSchema` on your own model) is
  marked for you to split rather than renamed, since your declaration does not
  change.
- The `streamable_http_client(...) as (read, write, _)` three-tuple to the v2
  two-tuple.
- The `mcp` requirement in `pyproject.toml` and `requirements*.txt`, to
  `>=2,<3`, wherever the current constraint cannot accept any v2 release. Only
  the version specifier changes; the name, extras, environment marker, and
  formatting keep your spelling. A constraint that already admits v2, a Poetry
  dependency table, and the removed `ws` extra are marked instead of guessed at.

## What it marks instead

Some changes cannot be made safely without information that is not in the file.
The codemod never guesses at these; it leaves them exactly as written and adds a
`# mcp-codemod:` comment explaining what to do:

- Removed APIs that have no drop-in replacement (`create_connected_server_and_client_session`,
  the WebSocket transport, `mcp.shared.progress`, `get_context()`), and imports
  of whole module namespaces v2 deleted (the removed experimental tasks
  API). Together with the renames these account for every public
  module v1 shipped, so an import is never left to fail unexplained.
- The v1 `mcp.types` names with no v2 home (`Cursor`, the `TASK_*` constants, the
  type-machinery aliases). `mcp_types` is not a name-superset of v1's `mcp.types`,
  so these are marked with their replacement instead of being rewritten into an
  import that cannot resolve.
- A `streamablehttp_client(...)` call used anywhere other than directly as a
  `with` item (for example through `AsyncExitStack.enter_async_context`): it now
  yields two values, not three, and only the inline `as (read, write, _)` form
  can be rewritten safely, so every other form is marked.
- Transport keywords on the `MCPServer` constructor (`host=`, `port=`,
  `stateless_http=`, ...), which moved to `run()` or one of the app methods. The
  right destination depends on how you start the server, so the kwarg is left in
  place -- v2 then fails loudly -- rather than silently dropped.
- Lowlevel `@server.call_tool()` decorators, which became `on_call_tool=`
  constructor arguments with a different handler signature. Rewriting the
  registration also means rewriting the handler body, which is yours to do.
- Renames the codemod applied but cannot prove are right: a camelCase rename
  whose receiver could plausibly not be an mcp type gets a `# mcp-codemod: review:`
  marker so you look at it instead of trusting it.

`--dry-run` writes nothing, and `--diff` prints a unified diff of every change;
combine the two to preview a run.
