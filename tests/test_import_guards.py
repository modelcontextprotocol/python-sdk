"""Import-cost ratchet: pins which heavy dependencies each entry point may load.

Every check runs in a fresh interpreter - this process has long since imported the whole
SDK, so its own `sys.modules` proves nothing - and asserts on the module footprint of a
single import. A hoisted or newly-eager import that regresses one of these promises fails
here instead of silently making startup slower for every downstream package.

The invariants (see also the "Import cost" section of AGENTS.md and docs/advanced/import-cost.md):

* `import mcp` is a lazy namespace: it loads no pydantic, no `mcp_types` and no `mcp`
  submodule; each `mcp.<name>` resolves its home module on first access.
* Client entry points never load the server stack, and the HTTP client stack
  (httpx2) loads only for the HTTP transports; a stdio-only client pays for neither.
* Transport-agnostic server entry points (`mcp.server`, the lowlevel `Server`,
  `MCPServer`, the stdio transport) never load the web stack (starlette,
  sse_starlette, uvicorn), the OpenTelemetry API or an HTTP client; those load when an
  HTTP app is built / a span is emitted / an `HttpResource` is read.
* Every documented module imports as the FIRST import of a fresh interpreter, without
  warnings (the lazy resolution must never depend on import order).
"""

from __future__ import annotations

import json
import os
import pkgutil
import subprocess
import sys

import mcp_types
import pytest

import mcp

# pydantic auto-loads every installed pydantic plugin (e.g. logfire, which imports
# opentelemetry) when the first model class is created. That is the environment's cost,
# not the SDK's, so the child interpreters run with plugins disabled to measure the
# SDK's own import graph.
CHILD_ENV = {**os.environ, "PYDANTIC_DISABLE_PLUGINS": "__all__"}

# Web/HTTP server-side stack that only HTTP transports may load.
HTTP_SERVER_STACK = ("starlette", "sse_starlette", "uvicorn", "python_multipart")

# Everything a client entry point must never load: the server side of the SDK, the web
# stack, and the auth/telemetry dependencies that only server-side code paths use.
CLIENT_BANNED = ("mcp.server", *HTTP_SERVER_STACK, "opentelemetry", "cryptography", "jwt")

# Everything a transport-agnostic server entry point must never load. `cryptography` backs
# the built-in request-state codec and loads with the first codec construction (`MCPServer()`
# builds one), never at import.
SERVER_BANNED = (*HTTP_SERVER_STACK, "opentelemetry", "httpx2", "jwt", "cryptography")

# Per-version wire-schema packages: loaded only when that protocol version is used.
WIRE_PACKAGES = ("mcp_types._v2025_11_25", "mcp_types._v2026_07_28")

IMPORT_GUARDS: list[tuple[str, tuple[str, ...]]] = [
    ("import mcp.types", (*CLIENT_BANNED, "httpx2", *WIRE_PACKAGES)),
    ("import mcp_types", (*CLIENT_BANNED, "httpx2", *WIRE_PACKAGES)),
    ("import mcp_types.methods", (*CLIENT_BANNED, "httpx2", *WIRE_PACKAGES)),
    ("from mcp.types import Tool", (*CLIENT_BANNED, "httpx2", *WIRE_PACKAGES)),
    ("import mcp.client", (*CLIENT_BANNED, "httpx2")),
    ("import mcp.client.stdio", (*CLIENT_BANNED, "httpx2")),
    ("import mcp.client.session", (*CLIENT_BANNED, "httpx2")),
    ("from mcp import Client", (*CLIENT_BANNED, "httpx2")),
    ("from mcp import ClientSession", (*CLIENT_BANNED, "httpx2")),
    # The HTTP client transports are the one place httpx2 belongs.
    ("import mcp.client.streamable_http", CLIENT_BANNED),
    ("import mcp.client.sse", CLIENT_BANNED),
    ("import mcp.server", SERVER_BANNED),
    ("import mcp.server.lowlevel", SERVER_BANNED),
    ("import mcp.server.stdio", SERVER_BANNED),
    ("import mcp.server.mcpserver", SERVER_BANNED),
    ("from mcp.server.mcpserver import MCPServer", SERVER_BANNED),
    ("from mcp import stdio_server", SERVER_BANNED),
]


def _run(code: str) -> str:
    """Run `code` in a fresh interpreter with warnings as errors and return its stdout."""
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=CHILD_ENV,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _modules_after(statement: str) -> set[str]:
    """Every module in `sys.modules` after running `statement` in a fresh interpreter."""
    probe = f"import json, sys\n{statement}\nprint(json.dumps(sorted(sys.modules)))"
    return set(json.loads(_run(probe)))


def _hits(loaded: set[str], banned: tuple[str, ...]) -> list[str]:
    """The banned packages (or submodules of them) that ended up loaded."""
    return sorted({p for p in banned for m in loaded if m == p or m.startswith(p + ".")})


def _documented_modules() -> list[str]:
    """Every public (documented) module: the same rule the API reference uses.

    A module is documented when no component of its dotted path is `_`-private
    (`scripts/docs/gen_ref_pages.py`). Optional-dependency modules that this environment
    cannot import are skipped, exactly as they are for any other test.
    """
    names: list[str] = []
    for pkg in (mcp, mcp_types):
        names.append(pkg.__name__)
        names.extend(
            info.name
            for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + ".")
            if not any(part.startswith("_") for part in info.name.split("."))
        )
    return sorted(names)


def test_bare_import_mcp_is_a_lazy_namespace():
    """`import mcp` loads no protocol types, no pydantic and no SDK submodule beyond the
    tiny lazy-loading helper the namespace itself is built with."""
    loaded = _modules_after("import mcp")
    mcpish = {m for m in loaded if m.startswith("mcp") or m.startswith("pydantic")}
    assert mcpish <= {"mcp", "mcp.shared", "mcp.shared._lazy"}, sorted(mcpish)


@pytest.mark.parametrize(("statement", "banned"), IMPORT_GUARDS, ids=[case[0] for case in IMPORT_GUARDS])
def test_entry_point_does_not_load_the_heavy_stacks_it_does_not_use(statement: str, banned: tuple[str, ...]):
    """Each entry point keeps the stacks it does not need out of its import graph."""
    assert _hits(_modules_after(statement), banned) == []


def test_first_url_client_is_what_loads_the_http_client_transport():
    """The deferred load happens where it is used: building the first URL `Client` (which
    only connects on `__aenter__`) is what imports httpx2 - and the server stack stays out."""
    probe = (
        "import json, sys\n"
        "from mcp import Client\n"
        "before = sorted(sys.modules)\n"
        "Client('http://localhost/mcp')\n"
        "print(json.dumps([before, sorted(sys.modules)]))\n"
    )
    before, after = (set(names) for names in json.loads(_run(probe)))
    assert _hits(before, (*CLIENT_BANNED, "httpx2")) == []
    assert _hits(after, ("httpx2",)) == ["httpx2"]
    assert _hits(after, CLIENT_BANNED) == []


def test_request_state_codec_is_what_loads_cryptography():
    """The deferred load happens where it is used: importing the server does not load
    `cryptography`; constructing an `MCPServer` (which builds the default request-state
    codec) is what does."""
    probe = (
        "import json, sys\n"
        "from mcp.server.mcpserver import MCPServer\n"
        "before = sorted(sys.modules)\n"
        "MCPServer('probe')\n"
        "print(json.dumps([before, sorted(sys.modules)]))\n"
    )
    before, after = (set(names) for names in json.loads(_run(probe)))
    assert _hits(before, SERVER_BANNED) == []
    assert _hits(after, ("cryptography",)) == ["cryptography"]
    assert _hits(after, HTTP_SERVER_STACK) == []


@pytest.mark.parametrize("module_name", _documented_modules())
def test_documented_module_imports_first_in_a_fresh_interpreter(module_name: str):
    """Every documented module imports cleanly and warning-free as a process's first
    import, so the lazy resolution never depends on something having been imported first."""
    if module_name.startswith("mcp.cli"):
        pytest.importorskip("typer")
    _run(f"import {module_name}")
