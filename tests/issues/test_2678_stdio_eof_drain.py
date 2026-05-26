import json
import subprocess
import sys
import textwrap
from pathlib import Path


def test_stdio_redirected_stdin_eof_drains_accepted_tool_responses(tmp_path: Path) -> None:
    server_py = tmp_path / "server.py"
    payload_jsonl = tmp_path / "payload.jsonl"
    response_jsonl = tmp_path / "response.jsonl"

    server_py.write_text(
        textwrap.dedent(
            """
            import asyncio

            from mcp.server.mcpserver import MCPServer

            mcp = MCPServer("repro")

            @mcp.tool()
            async def slow_echo(text: str) -> str:
                await asyncio.sleep(0.05)
                return text

            if __name__ == "__main__":
                mcp.run(transport="stdio")
            """
        ),
        encoding="utf-8",
    )
    payload_jsonl.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 0,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "repro", "version": "0.1"},
                        },
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "slow_echo", "arguments": {"text": "first"}},
                    }
                ),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "slow_echo", "arguments": {"text": "second"}},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with payload_jsonl.open("rb") as stdin, response_jsonl.open("wb") as stdout:
        completed = subprocess.run(
            [sys.executable, str(server_py)],
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    response_ids = {json.loads(line)["id"] for line in response_jsonl.read_text(encoding="utf-8").splitlines()}
    assert {0, 1, 2}.issubset(response_ids)
