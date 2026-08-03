"""What each entry point imports: a ratchet on the SDK's import graph."""

import os
import subprocess
import sys

import pytest

# pydantic auto-loads installed pydantic plugins (logfire pulls in opentelemetry) at the
# first model build. That is the environment's cost, not the SDK's, so the children run
# with plugins disabled to measure the SDK's own import graph.
_CHILD_ENV = {**os.environ, "PYDANTIC_DISABLE_PLUGINS": "__all__"}

_WEB_STACK = ("starlette", "sse_starlette", "uvicorn")

# What a transport-agnostic server entry point must not load: starlette is banned by its
# heavy subpackages rather than the root, because the auth context accessor still uses
# starlette's small typing leaf.
_SERVER_WEB_STACK = ("starlette.applications", "starlette.routing", "starlette.requests", "sse_starlette", "uvicorn")

# The generated per-version wire packages. No entry point loads them: a connection loads
# only its negotiated version's, on the first message it parses.
_WIRE_PACKAGES = ("mcp_types._v2025_11_25", "mcp_types._v2026_07_28")

# Entry statement -> package prefixes it must not load (on top of the wire packages).
IMPORT_GUARDS: dict[str, tuple[str, ...]] = {
    "import mcp": ("mcp.client", "mcp.server", *_WEB_STACK, "httpx2", "opentelemetry", "cryptography", "jwt"),
    "import mcp.client.stdio": ("mcp.server", "httpx2"),
    "import mcp.server.stdio": ("mcp.client", *_SERVER_WEB_STACK),
    "import mcp_types.methods": (),
}


@pytest.mark.parametrize("statement", IMPORT_GUARDS)
def test_entry_point_does_not_import_unrelated_stacks(statement: str) -> None:
    """SDK-defined: each entry point loads only what it needs, so a hoisted or newly-eager
    import fails here instead of silently slowing every startup. Runs in a fresh interpreter,
    since this process imported the whole SDK long ago."""
    probe = f"import sys\n{statement}\nprint(' '.join(sorted(sys.modules)))"
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False, timeout=30, env=_CHILD_ENV
    )
    assert result.returncode == 0, result.stderr
    loaded = result.stdout.split()
    banned = (*IMPORT_GUARDS[statement], *_WIRE_PACKAGES)
    hits = sorted(
        {module for module in loaded for prefix in banned if module == prefix or module.startswith(prefix + ".")}
    )
    assert hits == []
