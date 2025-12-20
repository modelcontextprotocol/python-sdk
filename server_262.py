#!/usr/bin/env python3
"""
Simple MCP server for reproducing issue #262.

This is a minimal MCP server that:
1. Handles initialize
2. Exposes a simple tool
3. Handles tool calls

Run: python server_262.py

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
"""

import json
import sys


def send_response(response: dict) -> None:
    """Send a JSON-RPC response to stdout."""
    print(json.dumps(response), flush=True)


def read_request() -> dict | None:
    """Read a JSON-RPC request from stdin."""
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def main() -> None:
    """Main server loop."""
    while True:
        request = read_request()
        if request is None:
            break

        method = request.get("method", "")
        request_id = request.get("id")

        if method == "initialize":
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "issue-262-server", "version": "1.0.0"},
                    },
                }
            )

        elif method == "notifications/initialized":
            # Notification, no response needed
            pass

        elif method == "tools/list":
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "greet",
                                "description": "A simple greeting tool",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string", "description": "Name to greet"}},
                                    "required": ["name"],
                                },
                            }
                        ]
                    },
                }
            )

        elif method == "tools/call":
            tool_name = request.get("params", {}).get("name", "")
            arguments = request.get("params", {}).get("arguments", {})

            if tool_name == "greet":
                name = arguments.get("name", "World")
                send_response(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"content": [{"type": "text", "text": f"Hello, {name}!"}], "isError": False},
                    }
                )
            else:
                send_response(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                    }
                )

        elif method == "ping":
            send_response({"jsonrpc": "2.0", "id": request_id, "result": {}})

        # Unknown method - send error for requests (have id), ignore notifications
        elif request_id is not None:
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )


if __name__ == "__main__":
    main()
