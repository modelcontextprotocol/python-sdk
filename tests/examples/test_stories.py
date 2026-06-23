"""Run every story's ``scenario`` over the in-process (transport × era × variant) matrix."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import anyio
import pytest

from tests.examples.conftest import MANIFEST, STORIES, STORIES_DIR, Hosted, Leg, story_cfg

pytestmark = pytest.mark.anyio


async def test_story(
    leg: Leg,
    cfg: dict[str, Any],
    hosted: Hosted,
    client_module: Any,
    scenario_kw: dict[str, Any],
) -> None:
    scenario = client_module.scenario
    with anyio.fail_after(cfg["timeout_s"]):
        async with hosted.connect(**scenario_kw) as client:
            args: list[Any] = [client]
            if cfg["needs_connect"] or leg.era == "in-body":
                args.append(hosted.connect)
            if cfg["needs_http"]:
                args.append(hosted.http)
            await scenario(*args)


def test_manifest_matches_filesystem() -> None:
    """Manifest [story.*] / [deferred] keys and on-disk story directories agree exactly."""
    dirs = {d.name for d in STORIES_DIR.iterdir() if d.is_dir() and not d.name.startswith(("_", "."))}
    runnable = {d for d in dirs if (STORIES_DIR / d / "client.py").exists()}
    in_manifest = set(STORIES)
    assert runnable == in_manifest, {"only_on_disk": runnable - in_manifest, "only_in_manifest": in_manifest - runnable}
    # README-only stub dirs must be exactly the [deferred] table.
    deferred_manifest = set(MANIFEST.get("deferred", {}))
    assert dirs - runnable == deferred_manifest, {
        "stub_dirs_missing_from_manifest": (dirs - runnable) - deferred_manifest,
        "deferred_entries_missing_dir": deferred_manifest - (dirs - runnable),
    }
    assert runnable.isdisjoint(deferred_manifest), "deferred stories must not have a client.py"


_ERAS = {"dual", "modern", "legacy", "dual-in-body"}
_TRANSPORTS = {"in-memory", "http-asgi"}
_SERVER_EXPORTS = {"factory", "app"}


def test_manifest_schema_valid() -> None:
    """Declared manifest values are mutually consistent with the story files."""
    for name in STORIES:
        cfg = story_cfg(name)
        assert "-" not in name, f"{name!r}: story directories must be underscored (R3)"
        assert cfg["era"] in _ERAS, f"{name!r}: era={cfg['era']!r} not in {_ERAS}"
        assert cfg["server_export"] in _SERVER_EXPORTS, f"{name!r}: server_export={cfg['server_export']!r}"
        assert set(cfg["transports"]) <= _TRANSPORTS, f"{name!r}: transports={cfg['transports']!r}"
        assert (STORIES_DIR / name / "__init__.py").exists(), f"{name!r}: missing __init__.py"
        if cfg["server_export"] == "factory":
            assert (STORIES_DIR / name / "server.py").exists(), f"{name!r}: missing server.py"
        else:
            assert "in-memory" not in cfg["transports"], f"{name!r}: server_export='app' cannot run in-memory"
        if cfg["needs_http"]:
            assert cfg["transports"] == ["http-asgi"], f"{name!r}: needs_http requires transports=['http-asgi']"
        ll = STORIES_DIR / name / "server_lowlevel.py"
        assert cfg["lowlevel"] == ll.exists(), f"{name!r}: lowlevel={cfg['lowlevel']} vs server_lowlevel.py on disk"


def test_scenario_arity_matches_manifest() -> None:
    """``scenario`` parameter count agrees with ``needs_connect``/``dual-in-body``/``needs_http``."""
    for name in STORIES:
        cfg = story_cfg(name)
        wants_connect = cfg["needs_connect"] or cfg["era"] == "dual-in-body"
        expected = 1 + int(wants_connect) + int(cfg["needs_http"])
        mod = importlib.import_module(f"stories.{name}.client")
        arity = len(inspect.signature(mod.scenario).parameters)
        assert arity == expected, f"{name}: arity={arity} expected={expected}"
