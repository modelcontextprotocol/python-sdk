"""Client-side scaffold for story examples.

A story's ``client.py`` imports ``Target`` (or ``TargetFactory``) for its ``main``
signature and calls ``run_client(main)`` from ``__main__``. The story owns the
``Client(target, mode=...)`` construction; this module only decides WHICH target
``__main__`` hands it.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeAlias
from urllib.parse import urlsplit

import anyio
import httpx

from mcp import StdioServerParameters, stdio_client
from mcp.client import Transport
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.shared.version import LATEST_MODERN_VERSION

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

Target: TypeAlias = "Server[Any] | MCPServer | Transport | str"
"""Anything ``Client(...)`` accepts: an in-process server, a ``Transport``, or an HTTP URL."""

TargetFactory = Callable[[], Target]
"""Yields a FRESH target against the same server/app on every call (``multi_connection`` stories)."""

AuthBuilder = Callable[[httpx.AsyncClient], httpx.Auth]
"""Builds an ``httpx.Auth`` bound to the in-process HTTP client (auth-story harness seam)."""


def argv_after(flag: str, *, default: str | None = None) -> str:
    """Return the argv token following ``flag``, or ``default`` when the flag is absent."""
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except ValueError:
        if default is None:
            raise SystemExit(f"missing required {flag}") from None
        return default


def target_from_args(file: str) -> TargetFactory:
    """Build a ``TargetFactory`` for the sibling server over the argv-selected transport.

    ``--http <url>`` targets that streamable-HTTP URL; ``--stdio`` (the default) spawns
    the sibling ``server.py`` as a fresh subprocess on each call. ``--server <stem>``
    selects ``<stem>.py`` (e.g. ``server_lowlevel``). ``file`` is the caller's ``__file__``.
    """
    if "--http" in sys.argv:
        url = argv_after("--http")
        return lambda: url
    # stdio is legacy-only until serve_stdio() lands; the modern arm is --http only for now.
    server = Path(file).parent / f"{argv_after('--server', default='server')}.py"
    params = StdioServerParameters(command=sys.executable, args=[str(server)])
    return lambda: stdio_client(params)  # becomes Client(params) once that overload lands


def _story_cfg(name: str) -> dict[str, Any]:
    """The manifest entry for the story ``name`` with ``[defaults]`` applied."""
    manifest: dict[str, Any] = tomllib.loads((Path(__file__).parent / "manifest.toml").read_text())
    return manifest["defaults"] | manifest["story"].get(name, {})


def _authed_targets(url: str, http: httpx.AsyncClient) -> TargetFactory:
    """Fresh streamable-HTTP transports over an already-authed ``httpx`` client."""
    return lambda: streamable_http_client(url, http_client=http)


def run_client(main: Callable[..., Awaitable[None]]) -> None:
    """Entry point for ``if __name__ == "__main__"`` in every ``client.py``.

    Builds the argv-selected target(s) for the story that defines ``main``, picks the
    era from argv, and calls ``main`` with an explicit ``mode=``. If the story module
    exports ``build_auth``, the ``--http`` target is routed through an ``httpx.AsyncClient``
    that carries the returned ``httpx.Auth``. Prints ``OK:``/``FAIL:`` to stderr, exits 0/1.
    """
    globals_ = getattr(main, "__globals__", {})
    file = str(globals_.get("__file__", "<unknown>"))
    name = Path(file).parent.name
    cfg = _story_cfg(name)
    targets = target_from_args(file)
    build_auth: AuthBuilder | None = globals_.get("build_auth")
    transport = "http" if "--http" in sys.argv else "stdio"
    # Never rely on the SDK's mode= default — be explicit. stdio is legacy-only until
    # the SDK's stdio entry can negotiate the era, so only --http gets a modern arm.
    era = "modern" if transport == "http" and "--legacy" not in sys.argv else "legacy"
    if cfg["era"] == "dual-in-body":
        # The story pins its connection modes inside ``main`` itself, so hand it the
        # real-user "auto" default and let those in-body pins decide. A hard version pin
        # here would skip the discover probe and leave ``server_info`` blank.
        era = "in-body"
    mode = {"modern": LATEST_MODERN_VERSION, "legacy": "legacy", "in-body": "auto"}[era]

    async def _run() -> None:
        with anyio.fail_after(cfg["timeout_s"]):
            if not cfg["needs_http"] and (build_auth is None or transport != "http"):
                await main(targets if cfg["multi_connection"] else targets(), mode=mode)
                return
            # Auth and needs_http stories want the raw httpx client underneath the transport:
            # build_auth threads an httpx.Auth onto it (Client(url, auth=...) doesn't exist
            # yet), and needs_http stories assert on raw responses, so root the client at the
            # server origin and relative paths like "/mcp" resolve.
            if transport != "http":
                raise SystemExit(f"{name} asserts on raw HTTP responses; run it with --http <url>")
            url = argv_after("--http")
            parts = urlsplit(url)
            async with httpx.AsyncClient(base_url=f"{parts.scheme}://{parts.netloc}") as http:
                make = targets
                if build_auth is not None:
                    http.auth = build_auth(http)
                    make = _authed_targets(url, http)
                target: Any = make if cfg["multi_connection"] else make()
                if cfg["needs_http"]:
                    await main(target, mode=mode, http=http)
                else:
                    await main(target, mode=mode)

    try:
        anyio.run(_run)
    except Exception:
        print(f"FAIL: {name} ({transport}/{era})", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1) from None
    print(f"OK: {name} ({transport}/{era})", file=sys.stderr)
    raise SystemExit(0)
