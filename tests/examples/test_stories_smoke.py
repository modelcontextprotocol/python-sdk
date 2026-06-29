"""Subprocess smoke for the story `__main__` paths.

The in-process matrix in `test_stories.py` never executes a story's `__main__` block, so
`run_client` / `run_server_from_args` / `run_app_from_args` and the real stdio + uvicorn
entries go unverified there. Runs the literal README commands: stdio, and bare `--http`
(`run_client` self-hosts the server on a real uvicorn socket).

lax no cover: gated on `MCP_EXAMPLES_SMOKE=1`, set on exactly one CI matrix cell
(ubuntu / 3.12 / locked — see `shared.yml`); other cells skip at collection, so the
per-job 100% coverage gate would otherwise fail.
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
# httpx in the spawned client honours these and mounts a SOCKS transport even for 127.0.0.1; strip for hermetic runs.
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
    with anyio.fail_after(60):
        async with await anyio.open_process(
            [sys.executable, "-m", *argv], cwd=_REPO_ROOT, env=_ENV, stdout=None, stderr=None
        ) as proc:
            await proc.wait()
            assert proc.returncode == 0
