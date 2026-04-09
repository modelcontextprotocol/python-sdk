# Development Guidelines

## Branching Model

<!-- TODO: drop this section once v2 ships and main becomes the stable line -->

- `main` is currently the V2 rework. Breaking changes are expected here — when removing or
  replacing an API, delete it outright and document the change in
  `docs/migration.md`. Do not add `@deprecated` shims or backward-compat layers
  on `main`.
- `v1.x` is the release branch for the current stable line. Backport PRs target
  this branch and use a `[v1.x]` title prefix.
- `README.md` is frozen at v1 (a pre-commit hook rejects edits). Edit
  `README.v2.md` instead.

## Package Management

- ONLY use uv, NEVER pip
- Installation: `uv add <package>`
- Running tools: `uv run --frozen <tool>`. Always pass `--frozen` so uv doesn't
  rewrite `uv.lock` as a side effect.
- Cross-version testing: `uv run --frozen --python 3.10 pytest ...` to run
  against a specific interpreter (CI covers 3.10–3.14).
- Upgrading: `uv lock --upgrade-package <package>`
- FORBIDDEN: `uv pip install`, `@latest` syntax
- Don't raise dependency floors for CVEs alone. The `>=` constraint already
  lets users upgrade. Only raise a floor when the SDK needs functionality from
  the newer version, and don't add SDK code to work around a dependency's
  vulnerability. See Kludex/uvicorn#2643 and python-sdk #1552 for reasoning.

## Code Quality

- Type hints required for all code
- Public APIs must have docstrings
- `src/mcp/__init__.py` defines the public API surface via `__all__`. Adding a
  symbol there is a deliberate API decision, not a convenience re-export.
- IMPORTANT: All imports go at the top of the file — inline imports hide
  dependencies and obscure circular-import bugs. Only exception: when a
  top-level import genuinely can't work (lazy-loading optional deps, or
  tests that re-import a module).

## Testing

- Framework: `uv run --frozen pytest`
- Async testing: use anyio, not asyncio
- Do not use `Test` prefixed classes, use functions
- IMPORTANT: Tests should be fast and deterministic. Prefer in-memory async execution;
  reach for threads only when necessary, and subprocesses only as a last resort.
- For end-to-end behavior, an in-memory `Client(server)` is usually the
  cleanest approach (see `tests/client/test_client.py` for the canonical
  pattern). For narrower changes, testing the function directly is fine. Use
  judgment.
- Test files mirror the source tree: `src/mcp/client/streamable_http.py` →
  `tests/client/test_streamable_http.py`. Add tests to the existing file for that module.
- Avoid `anyio.sleep()` with a fixed duration to wait for async operations. Instead:
  - Use `anyio.Event` — set it in the callback/handler, `await event.wait()` in the test
  - For stream messages, use `await stream.receive()` instead of `sleep()` + `receive_nowait()`
  - Exception: `sleep()` is appropriate when testing time-based features (e.g., timeouts)
- Wrap indefinite waits (`event.wait()`, `stream.receive()`) in `anyio.fail_after(5)` to prevent hangs
- Pytest is configured with `filterwarnings = ["error"]`, so warnings fail
  tests. Don't silence them with `filterwarnings` or `warnings.catch_warnings()`;
  fix the underlying cause instead.

### Coverage

CI requires 100% (`fail_under = 100`, `branch = true`).

- Full check: `./scripts/test` (~23s). Runs coverage + `strict-no-cover` on the
  default Python. Not identical to CI: CI also runs 3.10–3.14 × {ubuntu, windows},
  and some branch-coverage quirks only surface on specific matrix entries.
- Targeted check while iterating (~4s, deterministic):

  ```bash
  uv run --frozen coverage erase
  uv run --frozen coverage run -m pytest tests/path/test_foo.py
  uv run --frozen coverage combine
  uv run --frozen coverage report --include='src/mcp/path/foo.py' --fail-under=0
  UV_FROZEN=1 uv run --frozen strict-no-cover
  ```

  Partial runs can't hit 100% (coverage tracks `tests/` too), so `--fail-under=0`
  and `--include` scope the report. `strict-no-cover` has no false positives on
  partial runs — if your new test executes a line marked `# pragma: no cover`,
  even a single-file run catches it.

Avoid adding new `# pragma: no cover`, `# type: ignore`, or `# noqa` comments.
In tests, use `assert isinstance(x, T)` to narrow types instead of
`# type: ignore`. In library code (`src/`), a `# pragma: no cover` needs very
good reasoning — it usually means a test is missing. Audit before pushing:

```bash
git diff origin/main... | grep -E '^\+.*(pragma|type: ignore|noqa)'
```

What the existing pragmas mean:

- `# pragma: no cover` — line is never executed. CI's `strict-no-cover` fails if
  it IS executed. When your test starts covering such a line, remove the pragma.
- `# pragma: lax no cover` — excluded from coverage but not checked by
  `strict-no-cover`. Use for lines covered on some platforms/versions but not
  others.
- `# pragma: no branch` — excludes branch arcs only. coverage.py misreports the
  `->exit` arc for nested `async with` on Python 3.11+ (worse on 3.14/Windows).

## Breaking Changes

When making breaking changes, document them in `docs/migration.md`. Include:

- What changed
- Why it changed
- How to migrate existing code

Search for related sections in the migration guide and group related changes together
rather than adding new standalone sections.

## Formatting & Type Checking

- Format: `uv run --frozen ruff format .`
- Lint: `uv run --frozen ruff check . --fix`
- Type check: `uv run --frozen pyright`
- Pre-commit runs all of the above plus markdownlint, a `uv.lock` consistency
  check, and README checks — see `.pre-commit-config.yaml`

## Exception Handling

- **Always use `logger.exception()` instead of `logger.error()` when catching exceptions**
  - Don't include the exception in the message: `logger.exception("Failed")` not `logger.exception(f"Failed: {e}")`
- **Catch specific exceptions** where possible:
  - File ops: `except (OSError, PermissionError):`
  - JSON: `except json.JSONDecodeError:`
  - Network: `except (ConnectionError, TimeoutError):`
- **FORBIDDEN** `except Exception:` - unless in top-level handlers
