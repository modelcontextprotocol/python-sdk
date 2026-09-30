"""Type-check the installed client package and reject an invalid constructor argument."""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import mcp_client

assert importlib.util.find_spec("mcp") is None

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    consumer = root / "consumer.py"
    consumer.write_text(
        "from mcp_client import Client, StdioServerParameters\n"
        'Client("https://example.com/mcp")\n'
        'Client(StdioServerParameters(command="python"))\n'
        "Client(42)\n",
        encoding="utf-8",
    )
    config = root / "pyrightconfig.json"
    config.write_text(
        json.dumps(
            {
                "pythonPath": sys.executable,
                "typeCheckingMode": "strict",
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["pyright", "--project", str(config), "--outputjson", *mcp_client.__path__, str(consumer)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    diagnostics = json.loads(result.stdout)["generalDiagnostics"]
    errors = [diagnostic for diagnostic in diagnostics if diagnostic["severity"] == "error"]
    assert result.returncode == 1, result.stdout + result.stderr
    assert len(errors) == 1, result.stdout
    assert errors[0]["file"] == str(consumer), result.stdout
    assert errors[0]["range"]["start"]["line"] == 3, result.stdout
    assert errors[0]["rule"] == "reportArgumentType", result.stdout
