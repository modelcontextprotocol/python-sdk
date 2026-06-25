# pagination

Walk a paginated `resources/list` by hand: feed each result's `next_cursor`
back into `list_resources(cursor=...)` until it is `None`. The cursor is an
opaque server-chosen string — never parse it, and never terminate on a falsy
check (an empty string is a valid cursor under the spec).

## Run it

```bash
# stdio (default — the client spawns the server as a subprocess)
uv run python -m stories.pagination.client --server server_lowlevel

# against a running HTTP server
uv run python -m stories.pagination.server_lowlevel --http --port 8000 &
uv run python -m stories.pagination.client --http http://127.0.0.1:8000/mcp
```

Swap `server_lowlevel` → `server` to run against the `MCPServer` variant
(single page).

## What to look at

- `client.py` `main` — `async with Client(target, mode=mode) as client:` is the
  whole connection. The story owns the construction; `target` is whatever
  `Client()` accepts (an in-process server, a transport, or an HTTP URL) and
  the entry point picks it.
- `client.py` — `if page.next_cursor is None: break`. Termination is
  key-absent, not falsy; `while cursor:` would be a spec bug.
- `server_lowlevel.py` — the handler owns the cursor encoding (here: an
  integer offset as a string) and rejects an unrecognised cursor with
  `-32602 Invalid params`, the spec-recommended response.
- `server.py` — `MCPServer`'s decorator-registered resources are returned in
  a single page; the inbound `cursor` is accepted but ignored. The same client
  loop still terminates correctly after one request.

## Caveats

- **No `iter_*()` helper** — `Client` has no `iter_resources()` /
  `iter_tools()` async-iterator yet; the manual `while True` loop shown here
  is the supported pattern.
- **MCPServer is single-page** — `MCPServer` ignores `cursor` and never sets
  `next_cursor`. Whether it grows a `page_size=` knob or stays single-page by
  design is open; use the lowlevel server when you need to emit pages today.

## Spec

[Pagination — server utilities](https://modelcontextprotocol.io/specification/2025-11-25/server/utilities/pagination)

## See also

`resources/`, `tools/`, `prompts/` — every `*/list` method paginates the same
way. Reference test: `tests/interaction/lowlevel/test_pagination.py`.
