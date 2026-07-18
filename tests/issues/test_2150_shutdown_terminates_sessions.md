# Issue #2150 local verification notes

Upstream: https://github.com/modelcontextprotocol/python-sdk/issues/2150
SHA baseline: 3a6f2996cdd8358957479791e8b26198c07d6a75

## Bug (still present on main at scout time)

1. `StreamableHTTPSessionManager.run()` finally only:
   - `tg.cancel_scope.cancel()`
   - `_server_instances.clear()`
   without calling `transport.terminate()` on active sessions.

2. `StreamableHTTPServerTransport.terminate()` closed request/read/write streams but
   did **not** close `_sse_stream_writers`, leaving EventSourceResponse hung.

## Fix (local branch `atlas/fix-2150-shutdown-sessions`)

1. Manager shutdown: terminate each non-terminated transport before cancel.
2. Transport.terminate: close all SSE writers via close_sse_stream / close_standalone_sse_stream first.

## Tests added

- `test_terminate_closes_active_sse_stream_writers`
- `test_manager_shutdown_terminates_active_sessions`

in `tests/server/test_streamable_http_manager.py`.

## Local env note

This Atlas sandbox lacked `pip`/`uv`; tests were not executed here. Run upstream:

```bash
uv sync
uv run pytest tests/server/test_streamable_http_manager.py -k 2150 -q
# or by test name:
uv run pytest tests/server/test_streamable_http_manager.py::test_terminate_closes_active_sse_stream_writers -q
uv run pytest tests/server/test_streamable_http_manager.py::test_manager_shutdown_terminates_active_sessions -q
```

## Publication

Operator approval: none. Do not open PR until approved.
