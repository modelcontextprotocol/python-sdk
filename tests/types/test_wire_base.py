"""The deferred type-layer bases build on first use, and that first build is safe under concurrency."""

import inspect
import json
import os
import subprocess
import sys
from collections.abc import Callable

from mcp_types._wire_base import DeferredAdapter, DeferredModel
from pydantic import BaseModel, TypeAdapter

# The build lock only matters for the FIRST use of each model/adapter, which happens once per
# process, so the race runs in a fresh interpreter (this process built everything long ago).
# Barrier-released threads split four ways: some first-parse the same rows through `methods`
# (the shared per-target adapter cache), some first-use the module-level union adapters, some
# first-validate every never-built model, some first-generate the recursive JSON models' schema.
# Without the lock these interleavings raised on released pydantic (an adapter's schema
# regeneration iterating a class namespace another thread's completion mutates; a shared
# adapter's `__pydantic_core_schema__` swapping mid-build).
_RACE_PROBE = r"""
import json, sys, threading
sys.setswitchinterval(1e-6)  # maximise preemption inside the builds
import pydantic
import mcp_types._types as _types
import mcp_types._v2025_11_25 as v2025
import mcp_types._v2026_07_28 as v2026
import mcp_types.jsonrpc as jsonrpc
import mcp.client.session as session
from mcp_types import methods

MODULES = (_types, v2025, v2026, jsonrpc)
CLASSES = [
    obj for mod in MODULES for obj in vars(mod).values()
    if isinstance(obj, type) and issubclass(obj, pydantic.BaseModel) and obj.__module__ == mod.__name__
]
ADAPTERS = (
    _types.client_request_adapter, _types.client_result_adapter, _types.server_notification_adapter,
    _types.server_result_adapter, jsonrpc.jsonrpc_message_adapter, session.ClientResponse,
)
# the same server-result rows first-parsed from every thread: the SDK route through the
# shared per-target adapter cache and the union-schema regeneration over unbuilt members
ROWS = [
    ("ping", "2025-11-25", {}),
    ("tools/call", "2025-11-25", {"content": [{"type": "text", "text": "x"}], "isError": False}),
    ("tools/list", "2026-07-28", {"tools": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private"}),
]
N = 12
barrier = threading.Barrier(N)
errors, guard = [], threading.Lock()

def use_rows():
    for method, version, data in ROWS:
        methods.parse_server_result(method, version, data)

def use_adapters():
    for adapter in ADAPTERS:
        try:
            adapter.validate_python({"__probe__": 1})
        except pydantic.ValidationError:
            pass  # junk payload on purpose: the first-use build is what is under test

def use_models():
    for cls in CLASSES:
        try:
            cls.model_validate({"__probe__": 1})
        except (pydantic.ValidationError, TypeError):
            pass

def use_schemas():
    for cls in (v2026.JSONObject, v2026.JSONArray, v2026.JSONValue):
        cls.model_json_schema()

def worker(job):
    barrier.wait()
    try:
        job()
    except Exception as exc:
        with guard:
            errors.append(f"{type(exc).__name__}: {exc}"[:200])

jobs = (use_rows, use_adapters, use_models, use_schemas)
threads = [threading.Thread(target=worker, args=(jobs[i % 4],)) for i in range(N)]
for t in threads:
    t.start()
for t in threads:
    t.join()
incomplete = [c.__name__ for c in CLASSES if not c.__pydantic_complete__]
print(json.dumps({"n_classes": len(CLASSES), "errors": errors, "incomplete": incomplete}))
"""


def test_concurrent_first_use_of_the_deferred_type_layer_never_raises() -> None:
    """SDK-defined regression bar: twelve barrier-released threads first-using the never-built type
    layer at once (parsed rows through the adapter cache, union adapters, every model, the
    recursive JSON models' schema) raise nothing and leave every class complete."""
    result = subprocess.run(
        [sys.executable, "-c", _RACE_PROBE],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        # pydantic plugins (e.g. logfire) building models are the environment's cost, not ours
        env={**os.environ, "PYDANTIC_DISABLE_PLUGINS": "__all__"},
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["n_classes"] > 500  # the probe really covered the type layer
    assert report["errors"] == []
    assert report["incomplete"] == []


def _shape(fn: Callable[..., object]) -> list[tuple[str, str, object]]:
    empty = inspect.Parameter.empty
    return [
        (p.name, str(p.kind), "<required>" if p.default is empty else p.default)
        for p in inspect.signature(fn).parameters.values()
    ]


def test_deferred_bases_keep_pydantics_public_method_signatures() -> None:
    """SDK-defined: the lock-guarding overrides replicate pydantic's parameters exactly, so the
    typed signatures of these public methods are not erased on any model or adapter."""
    assert _shape(DeferredModel.model_rebuild) == _shape(BaseModel.model_rebuild)
    assert _shape(DeferredModel.model_json_schema) == _shape(BaseModel.model_json_schema)
    assert _shape(DeferredAdapter[int].rebuild) == _shape(TypeAdapter[int].rebuild)
    assert _shape(DeferredAdapter[int]) == _shape(TypeAdapter[int])
