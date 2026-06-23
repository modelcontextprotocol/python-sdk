"""Subprocess smoke for the story ``__main__`` paths.

The in-process matrix in ``test_stories.py`` never executes a story's
``if __name__ == "__main__"`` block, so ``run_client`` / ``run_server_from_args`` /
``run_app_from_args`` and the real stdio + uvicorn entries are unverified by
construction. This file proves that plumbing once over real subprocesses for two
stories (``tools`` over stdio, ``tools`` + ``bearer_auth`` over a real uvicorn
socket).

lax no cover: gated on ``MCP_EXAMPLES_SMOKE=1``, which CI sets on exactly one
matrix cell (ubuntu / 3.12 / locked — see ``shared.yml``). Every other cell
skips at collection, so the test bodies and the helpers they call are uncovered
there and the per-job 100% gate would otherwise fail.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import anyio
import pytest

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("MCP_EXAMPLES_SMOKE") != "1",
        reason="subprocess smoke runs on one CI cell only; set MCP_EXAMPLES_SMOKE=1",
    ),
]

_REPO_ROOT = Path(__file__).parents[2]
# httpx in the spawned client honours these and tries to mount a SOCKS transport even for
# 127.0.0.1; strip them so the smoke run is hermetic regardless of the caller's shell.
_PROXY_VARS = {v for base in ("all_proxy", "http_proxy", "https_proxy", "ftp_proxy") for v in (base, base.upper())}
_ENV = {k: v for k, v in os.environ.items() if k not in _PROXY_VARS}


def _free_port() -> int:  # pragma: lax no cover
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_listening(port: int) -> None:  # pragma: lax no cover
    """Poll ``127.0.0.1:port`` until it accepts; condition-based, not a fixed-duration wait."""
    while True:
        try:
            stream = await anyio.connect_tcp("127.0.0.1", port)
        except OSError:
            await anyio.sleep(0.05)
        else:
            await stream.aclose()
            return


async def _run_module(*argv: str) -> int:  # pragma: lax no cover
    async with await anyio.open_process(
        [sys.executable, "-m", *argv], cwd=_REPO_ROOT, env=_ENV, stdout=None, stderr=None
    ) as proc:
        await proc.wait()
        assert proc.returncode is not None
        return proc.returncode


async def test_tools_stdio_main_runs_end_to_end() -> None:  # pragma: lax no cover
    """``python -m stories.tools.client`` spawns the sibling server over real stdio and exits 0."""
    with anyio.fail_after(30):
        assert await _run_module("stories.tools.client") == 0


@pytest.mark.parametrize(
    ("story", "server_argv"),
    [
        ("tools", ("stories.tools.server", "--http")),
        ("bearer_auth", ("stories.bearer_auth.server",)),
    ],
    ids=["tools", "bearer_auth"],
)
async def test_http_main_runs_end_to_end(story: str, server_argv: tuple[str, ...]) -> None:  # pragma: lax no cover
    """Spawn the story's server on a real uvicorn socket, drive its client at it, assert exit 0."""
    port = _free_port()
    with anyio.fail_after(30):
        async with await anyio.open_process(
            [sys.executable, "-m", *server_argv, "--port", str(port)],
            cwd=_REPO_ROOT,
            env=_ENV,
            stdout=None,
            stderr=None,
        ) as server:
            try:
                await _wait_listening(port)
                assert await _run_module(f"stories.{story}.client", "--http", f"http://127.0.0.1:{port}/mcp") == 0
            finally:
                server.terminate()
                with anyio.move_on_after(5):
                    await server.wait()
                if server.returncode is None:
                    server.kill()
