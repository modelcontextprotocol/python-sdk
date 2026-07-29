"""Deferred (`defer_build`) models keep runtime introspection identical to eagerly-built ones,
and their first (lazy) build is safe under concurrency."""

import inspect
import json
import os
import subprocess
import sys
import typing

import pytest
from mcp_types import Implementation, Tool
from mcp_types._deferred import deferred_model
from mcp_types._types import MCPModel
from pydantic import BaseModel, ConfigDict


def test_never_used_model_reports_its_real_init_signature() -> None:
    """`inspect.signature()` completes the deferred build itself, so a model nobody has
    validated yet still reports its fields rather than pydantic's generic `(**data)`."""

    class Probe(MCPModel):
        first_name: str
        age: int = 0

    assert not Probe.__pydantic_complete__
    signature = inspect.signature(Probe)
    assert Probe.__pydantic_complete__  # the first signature access built it, once
    assert str(signature) == "(*, firstName: str, age: int = 0) -> None"


def test_deferred_signature_is_not_a_type_hint_and_is_class_only() -> None:
    """The lazy `__signature__` never leaks into `get_type_hints`, and instances do not
    expose one (matching `BaseModel`)."""

    class Probe(MCPModel):
        name: str

    assert "__signature__" not in typing.get_type_hints(Probe)
    assert not hasattr(Probe.model_construct(name="x"), "__signature__")  # still-deferred class
    assert not hasattr(Implementation(name="probe", version="1"), "__signature__")
    assert "__signature__" not in typing.get_type_hints(Tool)


def test_a_subclass_that_disables_defer_build_keeps_its_eager_signature() -> None:
    """A subclass may turn `defer_build` back off; it builds at class creation and keeps the
    signature pydantic gave it (the lazy one is only installed on still-deferred classes)."""

    class Eager(MCPModel):
        model_config = ConfigDict(defer_build=False)
        value: int

    assert Eager.__pydantic_complete__
    assert str(inspect.signature(Eager)) == "(*, value: int) -> None"


def test_decorated_root_model_covers_its_subclasses_too() -> None:
    """`@deferred_model` gives a `BaseModel`-derived deferred model - and every model that
    later subclasses it - an accurate pre-first-use signature."""

    @deferred_model
    class Root(BaseModel):
        model_config = ConfigDict(defer_build=True)
        x: int

    class Child(Root):
        y: str = "y"

    for cls, expected in ((Root, "(*, x: int) -> None"), (Child, "(*, x: int, y: str = 'y') -> None")):
        assert not cls.__pydantic_complete__
        assert str(inspect.signature(cls)) == expected


def test_the_decorator_refuses_a_root_that_would_not_defer_or_that_owns_a_subclass_hook() -> None:
    """`@deferred_model` marks a *deferred* hierarchy root and installs its own subclass hook:
    a class without `defer_build`, or one defining `__pydantic_init_subclass__` itself (which
    the installed hook would replace), is refused at decoration time."""

    class Eager(BaseModel):
        value: int

    class OwnsHook(BaseModel):
        model_config = ConfigDict(defer_build=True)
        value: int

        @classmethod
        def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
            raise NotImplementedError  # never runs: the decorator refuses the class first

    with pytest.raises(TypeError):
        deferred_model(Eager)
    with pytest.raises(TypeError):
        deferred_model(OwnsHook)


def test_unresolvable_model_falls_back_to_the_generic_signature() -> None:
    """A model whose build cannot complete (a forward reference that does not resolve at
    that point) reports the generic initializer signature, as pydantic does for any
    unbuilt model - and asking for the signature never raises."""

    class Pending(MCPModel):
        value: "Later"

    # `Later` is not defined yet, so the deferred build cannot complete here and the
    # class keeps pydantic's generic `(**data)` initializer signature.
    parameters = inspect.signature(Pending).parameters
    assert [(name, p.kind) for name, p in parameters.items()] == [("data", inspect.Parameter.VAR_KEYWORD)]
    assert not Pending.__pydantic_complete__
    with pytest.raises(NameError):
        Pending.model_rebuild()

    class Later(MCPModel):  # defined only afterwards: too late for `Pending`
        done: bool

    assert Later


# The lock only matters for the FIRST build of each model, which happens once per process:
# race a broad set of never-used models from a barrier-released thread pool inside fresh
# interpreters (this process built them long ago). Without the process-wide rebuild
# lock in `mcp_types._deferred`, a round like this raises in every run (pydantic <= 2.13
# does not lock `model_rebuild`; `AttributeError: __pydantic_core_schema__` and friends).
_RACE_PROBE = r"""
import inspect, json, sys, threading, traceback
sys.setswitchinterval(1e-6)  # maximize preemption inside the builds
import pydantic
import mcp_types._types as _types
import mcp_types._v2025_11_25 as v2025
import mcp_types._v2026_07_28 as v2026
import mcp_types.jsonrpc as jsonrpc
from mcp_types import methods
import mcp.client.session as session          # deferred module-level TypeAdapters
import mcp.server.mcpserver.server as mcpserver  # the SDK-layer deferred model roots
import mcp.server.mcpserver.prompts.base as prompts_base
import mcp.server.mcpserver.tools.base as tools_base
import mcp.server.mcpserver.resources.types as resource_types
import mcp.server.auth.settings as auth_settings
import mcp.shared.auth as shared_auth

def own_models(mod):
    return [o for o in vars(mod).values() if isinstance(o, type) and issubclass(o, pydantic.BaseModel)
            and o.__module__ == mod.__name__ and not o.__pydantic_complete__]

MODULES = (_types, v2025, v2026, jsonrpc, mcpserver, prompts_base, tools_base, resource_types, auth_settings,
           shared_auth)
CLASSES = [cls for mod in MODULES for cls in own_models(mod)]
ADAPTERS = [v for m in (_types, jsonrpc, session, prompts_base) for v in vars(m).values()
            if isinstance(v, pydantic.TypeAdapter)]
N = int(sys.argv[1])
barrier = threading.Barrier(N)
errors, lock = [], threading.Lock()

def first_use_everything():
    # The mutually recursive 2026 JSON models first: a FIRST json-schema generation
    # reads the core schema of each sibling it references while another thread may
    # still be completing that sibling.
    for cls in (v2026.JSONObject, v2026.JSONArray, v2026.JSONValue):
        cls.model_json_schema()
    for cls in CLASSES:
        try:
            cls.model_validate({"__probe__": 1})
        except (pydantic.ValidationError, TypeError):
            # junk payload on purpose: the first-use build is the point (TypeError = a
            # model with a custom __init__ rejecting the junk kwargs after the build)
            pass
    for adapter in ADAPTERS:
        try:
            adapter.validate_python({"__probe__": 1})
        except (pydantic.ValidationError, TypeError):
            pass
    methods.parse_client_request("ping", "2025-11-25", None)
    _types.Tool.model_json_schema()
    v2025.Root.model_json_schema()
    inspect.signature(_types.CallToolRequest)

def worker():
    barrier.wait()
    try:
        first_use_everything()
    except Exception as exc:
        with lock:
            errors.append(f"{type(exc).__name__}: {exc}"[:300])

threads = [threading.Thread(target=worker) for _ in range(N)]
for t in threads:
    t.start()
for t in threads:
    t.join()
incomplete = [c.__name__ for c in CLASSES if not c.__pydantic_complete__]
print(json.dumps({"n_classes": len(CLASSES), "errors": errors, "incomplete": incomplete}))
"""


def test_concurrent_first_use_of_deferred_models_never_raises() -> None:
    """Eight threads first-using a broad set of never-built models (monolith, both wire
    packages incl. the mutually recursive JSON models' first schema, JSON-RPC envelopes, the
    SDK's own models, the module-level adapters, first schema and signature access) build
    every class exactly once and raise nothing.

    The models must be unbuilt when the race starts, so the probe runs in fresh interpreters.
    """
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", _RACE_PROBE, "8"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            # pydantic plugins (e.g. logfire) building models are the environment's cost, not ours
            env={**os.environ, "PYDANTIC_DISABLE_PLUGINS": "__all__"},
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["n_classes"] > 200  # the probe really did cover the class set
        assert report["errors"] == []
        assert report["incomplete"] == []
