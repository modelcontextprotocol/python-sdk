"""Regression tests for issue #2233: stdio imports should stay optional on Windows."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_repo_python(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src_path if "PYTHONPATH" not in env else os.pathsep.join([src_path, env["PYTHONPATH"]])
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_server_stdio_import_does_not_load_client_stdio():
    script = textwrap.dedent("""
        import importlib
        import sys

        importlib.import_module("mcp.server.stdio")
        assert "mcp.client.stdio" not in sys.modules
    """)

    result = _run_repo_python(script)

    assert result.returncode == 0, result.stderr


def test_root_stdio_exports_handle_missing_pywin32():
    script = textwrap.dedent("""
        import builtins

        real_import = builtins.__import__
        blocked_modules = {"pywintypes", "win32api", "win32con", "win32job"}

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.split(".", 1)[0] in blocked_modules:
                raise ImportError(f"blocked import: {name}")
            return real_import(name, globals, locals, fromlist, level)

        builtins.__import__ = guarded_import
        try:
            from mcp import StdioServerParameters, stdio_client

            assert StdioServerParameters.__name__ == "StdioServerParameters"
            assert callable(stdio_client)
        finally:
            builtins.__import__ = real_import
    """)

    result = _run_repo_python(script)

    assert result.returncode == 0, result.stderr
