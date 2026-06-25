# prompts

Expose prompt templates with `@mcp.prompt()` and let clients autocomplete their
arguments with `@mcp.completion()`. `MCPServer` derives each prompt's
`arguments` (name + required) from the function signature. The client lists
prompts, completes the `language` argument of `code_review`, then renders both
prompts.

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.prompts.client

# against a running HTTP server
uv run python -m stories.prompts.server --http --port 8000 &
uv run python -m stories.prompts.client --http http://127.0.0.1:8000/mcp
```

## What to look at

- `client.py` `main` — the body opens with `async with Client(target,
  mode=mode) as client:`; `target` is anything `Client(...)` accepts (an
  in-process server, a `Transport`, or an HTTP URL).
- `server.py` `greet` vs `code_review` — return a bare `str` (wrapped as one
  user message) or a `list[Message]` for a multi-turn seed conversation.
- `server.py` `complete()` — one global handler dispatches on `ref` +
  `argument.name`; returning `None` becomes an empty completion. There is no
  per-argument `completer=` sugar yet.
- `server_lowlevel.py` — the same `Prompt` / `PromptArgument` descriptors and
  `GetPromptResult` built by hand; this is what `MCPServer` generates for you.
- `client.py` `complete(...)` — `argument` is a `{"name": ..., "value": ...}`
  dict, the only `Client` request method that takes a raw dict for a typed
  wire field.

## Caveats

`@mcp.prompt()` and `@mcp.completion()` need the parentheses — `@mcp.prompt`
without `()` raises a confusing `TypeError` at registration time.

## Spec

[Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts)
· [Completion](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/completion)

## See also

`tools/` (start here), `resources/` (the other `ref` kind completion accepts),
`pagination/` (`list_prompts` cursor loop).
