"""Discovery + parametrization for the example-stories matrix.

Reads ``examples/stories/manifest.toml`` and expands each story across
(server_variant × transport × era). The story modules are imported as
real packages (the ``mcp-example-stories`` workspace member installs ``stories``
editable), so pyright sees them and a signature change red-lines every story.

The HTTP-ASGI leg reuses the interaction suite's in-process bridge directly
from ``tests.interaction.transports._bridge`` (both live under ``tests/``); the
move to ``stories._shared.bridge`` is a later batch.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import stories
from starlette.applications import Starlette
from stories._harness import AuthBuilder, Connect
from stories._hosting import asgi_from

from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.version import LATEST_MODERN_VERSION
from tests.interaction.transports._bridge import StreamingASGITransport

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: lax no cover
    import tomli as tomllib

STORIES_DIR = Path(stories.__file__).parent
BASE_URL = "http://127.0.0.1:8000"

MANIFEST = tomllib.loads((STORIES_DIR / "manifest.toml").read_text())
DEFAULTS: dict[str, Any] = MANIFEST["defaults"]
STORIES: dict[str, dict[str, Any]] = MANIFEST["story"]

_ERA_TO_MODE = {"modern": LATEST_MODERN_VERSION, "legacy": "legacy"}
"""R8 maps era→mode. ``Client`` rejects handshake-era version strings, so
``legacy`` resolves to ``mode='legacy'`` rather than ``LATEST_HANDSHAKE_VERSION``."""


def story_cfg(name: str) -> dict[str, Any]:
    return DEFAULTS | STORIES.get(name, {})


def _expand_era(era: str) -> tuple[str, ...]:
    if era == "dual":
        return ("modern", "legacy")
    if era == "dual-in-body":
        return ("in-body",)
    return (era,)


@dataclass(frozen=True)
class Leg:
    story: str
    server_variant: str
    transport: str
    era: str

    @property
    def id(self) -> str:
        return "-".join((self.story, self.server_variant, self.transport, self.era))


def _legs() -> list[tuple[Leg, dict[str, Any]]]:
    out: list[tuple[Leg, dict[str, Any]]] = []
    for name in STORIES:
        cfg = story_cfg(name)
        variants = ["server"] + (["server_lowlevel"] if cfg["lowlevel"] else [])
        out.extend(
            (Leg(name, variant, transport, era), cfg)
            for variant in variants
            for transport in cfg["transports"]
            for era in _expand_era(cfg["era"])
        )
    return out


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "leg" not in metafunc.fixturenames:
        return
    params: list[Any] = []
    for leg, cfg in _legs():
        marks: list[pytest.MarkDecorator] = []
        if f"{leg.transport}:{leg.era}" in cfg["xfail"]:
            marks.append(pytest.mark.xfail(strict=True, reason="manifest xfail"))
        params.append(pytest.param(leg, marks=marks, id=leg.id))
    metafunc.parametrize("leg", params)


@pytest.fixture
def cfg(leg: Leg) -> dict[str, Any]:
    return story_cfg(leg.story)


@pytest.fixture
def server_module(leg: Leg) -> Any:
    return importlib.import_module(f"stories.{leg.story}.{leg.server_variant}")


@pytest.fixture
def client_module(leg: Leg) -> Any:
    return importlib.import_module(f"stories.{leg.story}.client")


def _client_kw(client_module: Any) -> dict[str, Any]:
    raw: dict[str, Any] | Callable[[], dict[str, Any]] | None = getattr(client_module, "client_kw", None)
    if raw is None:
        return {}
    return raw() if callable(raw) else dict(raw)


def _http_client_kw(client_module: Any) -> dict[str, Any]:
    """``httpx.AsyncClient(...)`` kwargs the story's client module wants threaded (G-http-kw)."""
    return dict(getattr(client_module, "http_client_kw", None) or {})


@dataclass
class Hosted:
    """One server/app instance hosted for the leg's whole duration.

    ``connect`` opens a fresh ``Client`` against that single instance on every
    call (G-connect-shared-server / G-event-store-per-app: state observed by one
    client is visible to the next). ``http`` is the shared raw ``httpx.AsyncClient``
    bound to the same ASGI app, or ``None`` on the in-memory leg.
    """

    connect: Connect
    http: httpx.AsyncClient | None


@pytest.fixture
async def hosted(
    leg: Leg, cfg: dict[str, Any], server_module: Any, client_module: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Hosted]:
    """Build the leg's server/app once and keep it running for the test.

    The leg's era pre-seeds ``mode=``; a scenario may override it per-call (R6
    ``dual-in-body`` opens both eras from the same body). Auth stories thread an
    ``httpx.Auth`` onto the bridge client via a module-level ``build_auth(http)``
    export and/or extra ``httpx.AsyncClient`` kwargs via ``http_client_kw`` (G3).
    """
    for key, value in cfg["env"].items():
        monkeypatch.setenv(key, value)
    mode = _ERA_TO_MODE.get(leg.era, "auto")
    path = cfg["mcp_path"]

    if leg.transport == "in-memory":
        server = server_module.build_server()

        @asynccontextmanager
        async def _connect(*, auth: AuthBuilder | None = None, **kw: Any) -> AsyncIterator[Client]:
            assert auth is None, "auth= is HTTP-only; restrict the story to transports=['http-asgi']"
            kw.setdefault("mode", mode)
            async with Client(server, **kw) as client:
                yield client

        yield Hosted(_connect, None)
        return

    # http-asgi: one Starlette app per leg. ``server_export="app"`` stories hand us the
    # app directly; ``"factory"`` stories are wrapped via ``asgi_from``. Either way the
    # app's own lifespan is what brings the session manager up (G-app-lifespan), and the
    # in-process bridge never fires ASGI lifespan events itself, so enter it explicitly.
    if cfg["server_export"] == "app":
        app: Starlette = server_module.build_app()
    else:
        app = asgi_from(server_module.build_server(), path=path)
    http_kw = _http_client_kw(client_module)
    build_auth: AuthBuilder | None = getattr(client_module, "build_auth", None)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL, **http_kw) as http_client,
    ):
        if build_auth is not None:
            http_client.auth = build_auth(http_client)

        @asynccontextmanager
        async def _connect(*, auth: AuthBuilder | None = None, **kw: Any) -> AsyncIterator[Client]:
            kw.setdefault("mode", mode)
            if auth is None:
                async with Client(streamable_http_client(f"{BASE_URL}{path}", http_client=http_client), **kw) as client:
                    yield client
                return
            # A scenario-supplied ``auth`` gets a fresh httpx client against the same app so
            # the second connection's auth flow doesn't share request-level state with the first.
            async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL, **http_kw) as fresh:
                fresh.auth = auth(fresh)
                async with Client(streamable_http_client(f"{BASE_URL}{path}", http_client=fresh), **kw) as client:
                    yield client

        yield Hosted(_connect, http_client)


@pytest.fixture
def scenario_kw(client_module: Any) -> dict[str, Any]:
    return _client_kw(client_module)
