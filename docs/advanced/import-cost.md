# Imports & startup time

`import mcp` is close to free, and every entry point loads only what it uses. You get that
without doing anything; this page is for when you want to know *what* loads *when*, how big the
deferred bills are, or when you want to move that work to a moment of your choosing.

## What loads when

The `mcp` package is a lazy namespace: `import mcp` binds no protocol types, no pydantic, and
none of the client or server modules. Each name resolves from its home module the first time you
touch it (`from mcp import Client` imports the client, `mcp.Tool` imports the types), and is then
an ordinary attribute. `from mcp import *`, `dir(mcp)` and object identity are unchanged; the
supported way to reach a submodule is still to import it (`import mcp.client.stdio`).

From there, each stack loads with the feature that needs it, once:

| Loaded on first use of | What loads | Roughly |
| --- | --- | --- |
| a URL `Client(...)` (or the SSE / streamable-HTTP client modules) | the HTTP client stack (`httpx2`) | ~60 ms |
| `streamable_http_app()` / `sse_app()` / `custom_route()` | the web stack (`starlette`, `sse_starlette`, `uvicorn`) | ~55 ms |
| the first message parsed for a protocol version | that version's wire-schema package (`mcp_types._v2025_11_25` / `_v2026_07_28`) | ~50 ms |
| the first construction, validation or JSON schema of a model | that model's pydantic validator (`defer_build=True`) | ~0.3 ms per model |
| the first server span | the OpenTelemetry API | ~7 ms |
| the first `MCPServer(...)` (its default `requestState` codec) | `cryptography` | ~10 ms |
| the first OAuth-enabled server | the OAuth provider models | ~10 ms |

(The magnitudes are single-machine measurements; expect the same shape, not the same numbers.)

None of these is per request. Each is a one-time cost paid where the work happens, and the
steady state afterwards is identical to having loaded it up front. Client code never loads the
server stack, and a stdio server never loads the web stack. Concretely, a fresh process pays
about **+130 ms once on its first in-memory connection and tool call** compared to a process that
built everything at import — the same work moved, not added — while `import mcp` itself dropped
from ~600 ms to ~3 ms and a typical `from mcp.types import ...` from ~600 ms to ~130 ms.

## Prewarming

A long-running host that would rather pay the deferred work at startup than on its first
connection calls `mcp.warm(version)` from its startup hook, naming the protocol version its
clients negotiate:

```python
--8<-- "docs_src/import_cost/tutorial001.py"
```

`warm(version)` builds the version-independent validators (the `mcp.types` models, the JSON-RPC
envelopes and the routing union adapters, ~50 ms) and imports that protocol version's wire package
and builds the routing surface a connection at that version uses (~+100 ms), so the first
connection finds everything built: measured, a host's first connection (initialize plus the first
tools/resources/prompts requests) drops from ~200 ms of one-time builds to ~65 ms, within a
millisecond of a steady-state connection. Name the version your transport negotiates: stdio and
streamable-HTTP sessions negotiate `2025-11-25` today, the in-memory `Client` `2026-07-28`.

The two other spellings are narrower and wider:

- `warm()` with no version builds only the version-independent set; the first connection still
  imports and builds its version's routing surface.
- `warm(all_versions=True)` warms every known version's routing surface, for a proxy or gateway
  serving clients of both eras.

The models are always completed before the adapters that reference them, nothing is built twice,
and repeat calls are no-ops. The returned `WarmReport` (a frozen dataclass: `models`, `adapters`,
`elapsed_ms`) counts what a call built, for logging. Do it once, at startup: nothing in the SDK
calls `warm()` for you, and importing the SDK stays fast either way.

An HTTP server needs nothing extra for its transport: building the app (`streamable_http_app()`) at
startup is exactly the moment its web stack loads anyway. An `MCPServer`'s own settings, tool and
prompt models build when the server object and its tools are constructed, which is startup work in
its own right.

## FAQ

**A pydantic plugin (e.g. `logfire`) is installed and `import mcp.types` is slow.** pydantic
auto-loads every installed plugin the first time a model class is created, and a few of the SDK's
generic base classes are created at import; with `logfire` installed that adds its import
(~200 ms) to `import mcp.types`. Set `PYDANTIC_DISABLE_PLUGINS=__all__` (or list the plugins you do
want) to keep it out of your import path. `import mcp` alone is unaffected.

**`Model.__pydantic_complete__` is `False` right after import.** Expected: the model builds on
first use. Code that checks the flag and then calls `Model.model_rebuild()` still works (the call is
a no-op once built); code asserting the flag at import will trip. `mcp.warm()` completes them all if
you need that up front.

**A subclass I defined inside a function shows `(**data)` from `inspect.signature()`.** The SDK's
models complete their build (and their real signature) on the first `inspect.signature()` access,
but a class defined in a *local* namespace whose annotations reference other locals cannot resolve
those from outside that function, so it keeps pydantic's generic signature until it is first used
where the names resolve. Module-level subclasses are unaffected.

**Bundling with PyInstaller / Nuitka / cx_Freeze.** The per-version wire-schema packages
(`mcp_types._v2025_11_25`, `mcp_types._v2026_07_28`) and the SDK's submodules are imported lazily. The
imports are still present in the bytecode, so import scanners generally find them; if your bundler
does not, add the packages to its hidden imports (PyInstaller: `--hidden-import mcp_types._v2026_07_28`,
and `--collect-submodules mcp` for the SDK's own lazily-resolved submodules).

**`typing.get_type_hints()` on the HTTP app builders raises `NameError`.** The Starlette-owned
annotations of `MCPServer.sse_app` / `streamable_http_app` (and the lowlevel `Server`'s
`streamable_http_app`) are typing-only, since evaluating them would import the web stack. Every
SDK-owned name in those signatures still resolves; supply starlette's names via `localns=` if you
need the full hints evaluated. Note that evaluating hints imports what they name:
`typing.get_type_hints(mcp.Client)` resolves `Client.server`'s annotation and so imports
`mcp.server`. See the [migration guide](../migration.md#import-graph-and-startup).

**Locks around the first (deferred) build.** A model's first build - and the JSON-schema generation
of a not-yet-built model - runs under one process-wide reentrant lock, so concurrent first uses build
each model exactly once instead of racing (the same design pydantic itself adopted for its own
`model_rebuild`). Two consequences: don't hold your own lock across a model's first use or inside a
custom `__get_pydantic_core_schema__` / subclass hook and then take that same lock elsewhere while
another thread first-uses a model (an ordinary lock-order inversion), and a thread that is mid-build
during `os.fork()` leaves the child's lock held (the standard fork-with-threads caveat). Calling
`mcp.warm(version)` at startup builds everything on one thread and makes concurrent first builds
impossible in the first place. Once a pydantic release with a thread-safe `model_rebuild` is the
SDK's dependency floor, the SDK's lock will be dropped.
