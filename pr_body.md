## Summary
- Changes the default `encoding_error_handler` in `StdioServerParameters` from `"strict"` to `"replace"`.
- Malformed UTF-8 bytes from a child server stdout previously crashed the client transport with `UnicodeDecodeError`.
- With `"replace"`, invalid bytes become U+FFFD and the line fails JSON-RPC validation, which is surfaced as an in-stream `Exception` that the session can handle.
- This mirrors the server-side stdio hardening from PR #2302.

## Test Plan
- [x] Reproduced the crash with a child process emitting `\xff\xfe\n` followed by valid JSON-RPC.
- [x] Verified the fix: first item is a `ValidationError`, second item is the valid `SessionMessage`.
- [x] Added regression test `test_invalid_utf8_from_the_server_surfaces_as_an_in_stream_exception`.
- [x] Full `tests/client/test_stdio.py` suite passes (34 passed, 1 skipped).

## Notes
- Fixes #2454
- Scope intentionally small.
