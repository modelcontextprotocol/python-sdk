"""The `mcp` package binds its client/server names, `mcp.types`, and its subpackages lazily (PEP 562)."""

import json
import subprocess
import sys

# Runs in a fresh interpreter: this test process imported the client/server stacks
# long ago, so only a clean one can observe first-access resolution and caching.
_LAZY_ACCESS_PROBE = """
import json, sys
import mcp
report = {
    "client_is_home_object": mcp.Client is sys.modules["mcp.client.client"].Client,
    "client_cached_in_namespace": "Client" in vars(mcp),
    "types_is_module": mcp.types is sys.modules["mcp.types"],
    "subpackage_chain": mcp.client.session.ClientSession.__name__,
    "dir_lists_every_all_name": set(mcp.__all__) <= set(dir(mcp)),
    "unresolvable_all_names": [n for n in mcp.__all__ if getattr(mcp, n, None) is None],
}
try:
    mcp.Toool
except AttributeError as exc:
    report["typo_error"] = str(exc)
print(json.dumps(report))
"""


# Runs in a fresh interpreter (each first access imports; a warm process has nothing to race).
# All threads are released at the same instant so their first-access imports genuinely overlap.
_THREADED_FIRST_ACCESS_PROBE = """
import json, sys, threading
sys.setswitchinterval(1e-6)  # maximise preemption inside the imports
import mcp
names = ["Client", "ClientSession", "ClientSessionGroup", "StdioServerParameters", "stdio_client",
         "ServerSession", "stdio_server", "InputRequiredRoundsExceededError", "types", "client", "server"]
barrier = threading.Barrier(len(names))
errors, resolved = [], {}

def first_access(name):
    barrier.wait()
    try:
        resolved[name] = getattr(mcp, name).__name__
    except BaseException as exc:  # an import deadlock raises importlib's _DeadlockError, a RuntimeError
        errors.append(f"{name}: {type(exc).__name__}: {exc}")

threads = [threading.Thread(target=first_access, args=(n,), daemon=True) for n in names]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join(20)
print(json.dumps({"errors": errors, "hung": [t.name for t in threads if t.is_alive()],
                  "resolved": sorted(resolved)}))
"""


def test_concurrent_first_access_of_different_lazy_names_never_deadlocks():
    """SDK-defined regression bar: threads that first-access different lazy `mcp.<name>`s at
    the same instant all resolve them. An eager `import mcp` used to serialise these imports;
    the lazy resolution must not invert the import locks and raise a threaded-import deadlock."""
    result = subprocess.run(
        [sys.executable, "-c", _THREADED_FIRST_ACCESS_PROBE], capture_output=True, text=True, check=False, timeout=60
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["errors"] == []
    assert report["hung"] == []
    assert report["resolved"] == sorted(
        [
            "Client",
            "ClientSession",
            "ClientSessionGroup",
            "InputRequiredRoundsExceededError",
            "ServerSession",
            "StdioServerParameters",
            "client",
            "server",
            "stdio_client",
            "stdio_server",
            "types",
        ]
    )


def test_lazy_names_resolve_to_their_home_objects_and_cache_on_first_access():
    """SDK-defined: a lazy `mcp.<name>` is the object from its home module and is stored in the
    package namespace once resolved; `mcp.types` and the `mcp.client` subpackage bind on first
    access; `dir(mcp)` lists every `__all__` name and every `__all__` name resolves (so the lazy
    tables cannot drift from `__all__`); and an unknown name is a plain AttributeError."""
    result = subprocess.run(
        [sys.executable, "-c", _LAZY_ACCESS_PROBE], capture_output=True, text=True, check=False, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "client_is_home_object": True,
        "client_cached_in_namespace": True,
        "types_is_module": True,
        "subpackage_chain": "ClientSession",
        "dir_lists_every_all_name": True,
        "unresolvable_all_names": [],
        "typo_error": "module 'mcp' has no attribute 'Toool'",
    }
