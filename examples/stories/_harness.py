"""Client-side scaffold for story examples.

A story's ``client.py`` imports ``Target`` (or ``TargetFactory``) for its ``main``
signature and calls ``run_client(main)`` from ``__main__``. The story owns the
``Client(target, mode=...)`` construction; this module only decides WHICH target
``__main__`` hands it.
"""

from __future__ import annotations

import socket
import sys
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
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


def target_from_args(file: str, url: str | None) -> TargetFactory:
    """Build a ``TargetFactory`` for the sibling server of the ``client.py`` at ``file``.

    ``url`` (already resolved by ``run_client``) targets that streamable-HTTP endpoint; ``None``
    spawns ``<stem>.py`` over stdio per call, ``<stem>`` from ``--server`` (default ``server``).
    """
    if url is not None:
        return lambda: url
    # stdio is legacy-only until serve_stdio() lands; the modern arm is --http only for now.
    server = Path(file).parent / f"{argv_after('--server', default='server')}.py"
    params = StdioServerParameters(command=sys.executable, args=[str(server)])
    return lambda: stdio_client(params)  # becomes Client(params) once that overload lands


def _explicit_http_url() -> str | None:
    """The URL token after ``--http``, or ``None`` when the flag stands alone (self-host)."""
    rest = sys.argv[sys.argv.index("--http") + 1 :]
    return rest[0] if rest and not rest[0].startswith("-") else None


def _free_port() -> int:
    """An OS-assigned free TCP port, released for the server subprocess to re-bind."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _accepting(port: int) -> bool:
    """Whether something accepts a TCP connect on ``127.0.0.1:port`` right now."""
    try:
        stream = await anyio.connect_tcp("127.0.0.1", port)
    except OSError:
        return False
    await stream.aclose()
    return True


@asynccontextmanager
async def _self_hosted(name: str, cfg: dict[str, Any]) -> AsyncIterator[str]:
    """Serve the story's sibling server from a subprocess on a port this process owns; yield its URL.

    Readiness is the first accepted TCP connect (bounded by ``run_client``'s
    ``anyio.fail_after``); exiting terminates the subprocess. Nothing to background or kill.
    A subprocess that dies before serving, or a ``fixed_port`` someone else already holds,
    is a loud ``SystemExit`` rather than a hang or a run against the wrong server.
    """
    port: int = cfg["fixed_port"] or _free_port()
    if cfg["fixed_port"] and await _accepting(port):
        # The readiness probe below can't tell our child from a server already on the
        # story's pinned port, so a foreign listener would be tested in its place.
        raise SystemExit(
            f"{name} self-hosts on :{port} but something is already serving there; "
            f"stop it, or connect to it with --http <url>"
        )
    module = f"stories.{name}.{argv_after('--server', default='server')}"
    serve = ["--http"] if cfg["server_export"] == "factory" else []
    argv = [sys.executable, "-m", module, *serve, "--port", str(port)]
    async with await anyio.open_process(argv, stdout=None, stderr=None) as server:
        try:
            while server.returncode is None and not await _accepting(port):
                await anyio.sleep(0.05)
            if server.returncode is not None:
                raise SystemExit(f"{module} exited {server.returncode} before serving on :{port}")
            yield f"http://127.0.0.1:{port}{cfg['mcp_path']}"
        finally:
            if server.returncode is None:
                server.terminate()


def _story_cfg(name: str) -> dict[str, Any]:
    """The manifest entry for the story ``name`` with ``[defaults]`` applied."""
    manifest: dict[str, Any] = tomllib.loads((Path(__file__).parent / "manifest.toml").read_text())
    return manifest["defaults"] | manifest["story"].get(name, {})


def _authed_targets(url: str, http: httpx.AsyncClient) -> TargetFactory:
    """Fresh streamable-HTTP transports over an already-authed ``httpx`` client."""
    return lambda: streamable_http_client(url, http_client=http)


def run_client(main: Callable[..., Awaitable[None]]) -> None:
    """Entry point for ``if __name__ == "__main__"`` in every ``client.py``.

    Resolves the argv target — stdio (the default), ``--http <url>`` for a server you run, or
    bare ``--http`` to self-host the sibling server in a subprocess it owns — and calls ``main``
    with an explicit ``mode=``. A ``build_auth`` export auths the HTTP target. ``OK``/``FAIL``, exit 0/1.
    """
    globals_ = getattr(main, "__globals__", {})
    file = str(globals_.get("__file__", "<unknown>"))
    name = Path(file).parent.name
    cfg = _story_cfg(name)
    build_auth: AuthBuilder | None = globals_.get("build_auth")
    transport = "http" if "--http" in sys.argv else "stdio"
    if cfg["server_export"] == "app" and transport != "http":
        raise SystemExit(
            f"{name} exports an ASGI app (no stdio entry point); self-host it over HTTP:\n"
            f"  python -m stories.{name}.client --http"
        )
    if cfg["needs_http"] and transport != "http":
        raise SystemExit(f"{name} asserts on raw HTTP responses; run it with --http")
    explicit_url = _explicit_http_url() if transport == "http" else None
    # The era is an axis of the story matrix, so ``mode=`` is always passed explicitly
    # even though it often matches the ``Client`` default of "auto". stdio is legacy-only
    # until the SDK's stdio entry can negotiate the era, so only --http gets a modern arm.
    era = "modern" if transport == "http" and "--legacy" not in sys.argv else "legacy"
    if cfg["era"] == "dual-in-body":
        # The story pins its connection modes inside ``main`` itself, so hand it "auto"
        # (the ``Client`` default) and let those in-body pins decide. A hard version pin
        # here would skip the discover probe and leave ``server_info`` blank.
        era = "in-body"
    mode = {"modern": LATEST_MODERN_VERSION, "legacy": "legacy", "in-body": "auto"}[era]

    async def _run() -> None:
        with anyio.fail_after(cfg["timeout_s"]):
            async with AsyncExitStack() as stack:
                url = explicit_url
                if transport == "http" and url is None:
                    url = await stack.enter_async_context(_self_hosted(name, cfg))
                targets = target_from_args(file, url)
                if url is None or (build_auth is None and not cfg["needs_http"]):
                    await main(targets if cfg["multi_connection"] else targets(), mode=mode)
                    return
                # Auth and needs_http stories want the raw httpx client underneath the transport:
                # build_auth threads an httpx.Auth onto it (Client(url, auth=...) doesn't exist
                # yet), and needs_http stories assert on raw responses, so root the client at the
                # server origin and relative paths like "/mcp" resolve.
                parts = urlsplit(url)
                base = f"{parts.scheme}://{parts.netloc}"
                http = await stack.enter_async_context(httpx.AsyncClient(base_url=base))
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
