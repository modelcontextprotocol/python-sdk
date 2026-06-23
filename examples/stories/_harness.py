"""Client-side scaffold for story examples.

A story's ``client.py`` imports only from here. The ``Connect`` factory and
``run_client`` ride the locked ``Client(transport, mode=...)`` surface; the one
volatile line is the stdio wrap (marked inline).
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

import anyio
import httpx

from mcp import StdioServerParameters, stdio_client
from mcp.client import Client
from mcp.shared.version import LATEST_MODERN_VERSION

Scenario = Callable[[Client], Awaitable[None]]
ScenarioWithConnect = Callable[[Client, "Connect"], Awaitable[None]]
AuthBuilder = Callable[[httpx.AsyncClient], httpx.Auth]
"""Builds an ``httpx.Auth`` bound to the in-process HTTP client (auth-story harness seam)."""


class Connect(Protocol):
    """A factory yielding a connected ``Client``; accepts the same kwargs as ``Client``.

    ``auth`` is the HTTP-only escape hatch for auth stories: when given, the factory
    builds a fresh ``httpx.AsyncClient`` against the same app, applies ``auth(http)``
    to it, and wraps the result in ``streamable_http_client`` before entering ``Client``.
    """

    def __call__(self, *, auth: AuthBuilder | None = None, **client_kw: Any) -> AbstractAsyncContextManager[Client]: ...


def argv_after(flag: str, *, default: str | None = None) -> str:
    """Return the argv token following ``flag``, or ``default`` when the flag is absent."""
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except ValueError:
        if default is None:
            raise SystemExit(f"missing required {flag}") from None
        return default


def connect_from_args(file: str) -> Connect:
    """Build a ``Connect`` targeting the sibling server over the argv-selected transport.

    ``--http <url>`` connects over streamable HTTP; ``--stdio`` (the default) spawns the
    sibling ``server.py`` as a subprocess. ``--server <stem>`` selects ``<stem>.py``
    (e.g. ``server_lowlevel``). ``--legacy`` pins the handshake era; otherwise the
    modern era is used. ``file`` is the caller's ``__file__``.
    """
    here = Path(file).parent
    server_stem = argv_after("--server", default="server")
    # Never rely on the SDK's mode= default — be explicit. stdio is legacy-only until
    # the SDK's stdio entry can negotiate the era; the modern arm is --http only for now.
    if "--http" in sys.argv:
        mode = "legacy" if "--legacy" in sys.argv else LATEST_MODERN_VERSION
    else:
        mode = "legacy"  # stdio gains a modern arm once serve_stdio() lands

    @asynccontextmanager
    async def _connect(*, auth: AuthBuilder | None = None, **client_kw: Any) -> AsyncIterator[Client]:
        assert auth is None, "auth= via connect_from_args is not wired; auth stories own their __main__"
        client_kw.setdefault("mode", mode)
        target: Any
        if "--http" in sys.argv:
            target = argv_after("--http")
        else:
            params = StdioServerParameters(command=sys.executable, args=[str(here / f"{server_stem}.py")])
            target = stdio_client(params)  # becomes Client(params) once that overload lands
        async with Client(target, **client_kw) as client:
            yield client

    return _connect


def run_client(
    scenario: Scenario | ScenarioWithConnect,
    *,
    connect: Connect,
    needs_connect: bool = False,
    **client_kw: Any,
) -> None:
    """Entry point for ``if __name__ == "__main__"`` in every ``client.py``.

    Runs ``scenario`` inside a connected client; prints ``OK:``/``FAIL:`` to stderr and
    exits 0/1. ``needs_connect=True`` passes ``connect`` as the second argument so the
    scenario can open additional clients.
    """
    file = getattr(scenario, "__globals__", {}).get("__file__", "<unknown>")
    name = Path(file).parent.name
    transport = "http" if "--http" in sys.argv else "stdio"
    era = "modern" if transport == "http" and "--legacy" not in sys.argv else "legacy"

    async def _main() -> None:
        with anyio.fail_after(30):
            async with connect(**client_kw) as client:
                if needs_connect:
                    await scenario(client, connect)  # type: ignore[call-arg]
                else:
                    await scenario(client)  # type: ignore[call-arg]

    try:
        anyio.run(_main)
    except Exception:
        print(f"FAIL: {name} ({transport}/{era})", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1) from None
    print(f"OK: {name} ({transport}/{era})", file=sys.stderr)
    raise SystemExit(0)
