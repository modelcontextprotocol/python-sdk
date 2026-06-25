"""Subprocess smoke for the story ``__main__`` paths.

The in-process matrix in ``test_stories.py`` never executes a story's
``if __name__ == "__main__"`` block, so ``run_client`` / ``run_server_from_args`` /
``run_app_from_args`` and the real stdio + uvicorn entries are unverified by
construction. This file proves that plumbing by running the literal commands the
story READMEs print: stdio (``run_client`` spawns the server over stdio) and bare
``--http`` (``run_client`` self-hosts the server on a real uvicorn socket on a
port it owns, then terminates it).

lax no cover: gated on ``MCP_EXAMPLES_SMOKE=1``, which CI sets on exactly one
matrix cell (ubuntu / 3.12 / locked — see ``shared.yml``). Every other cell
skips at collection, so the test body is uncovered there and the per-job 100%
gate would otherwise fail.
"""

from __future__ import annotations

import os
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


@pytest.mark.parametrize(
    "argv",
    [
        ("stories.tools.client",),
        ("stories.tools.client", "--http"),
        ("stories.bearer_auth.client", "--http"),
    ],
    ids=["tools-stdio", "tools-http", "bearer_auth-http"],
)
async def test_story_main_runs_end_to_end(argv: tuple[str, ...]) -> None:  # pragma: lax no cover
    """``python -m <story>.client [--http]`` (the README command) exits 0 over a real subprocess."""
    with anyio.fail_after(60):
        async with await anyio.open_process(
            [sys.executable, "-m", *argv], cwd=_REPO_ROOT, env=_ENV, stdout=None, stderr=None
        ) as proc:
            await proc.wait()
            assert proc.returncode == 0
