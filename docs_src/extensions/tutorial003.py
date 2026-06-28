from collections.abc import Sequence
from typing import Any

from mcp import Client
from mcp.server.extension import Extension, ToolBinding
from mcp.server.mcpserver import MCPServer


def stamp(text: str) -> str:
    """Stamp a message with the office seal."""
    return f"[stamped] {text}"


class Stamps(Extension):
    """A purely additive extension: one tool, one capability entry."""

    identifier = "com.example/stamps"

    def settings(self) -> dict[str, Any]:
        return {"sealed": True}

    def tools(self) -> Sequence[ToolBinding]:
        return [ToolBinding(fn=stamp)]


mcp = MCPServer("post-office", extensions=[Stamps()])


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.extensions)
        # {'com.example/stamps': {'sealed': True}}
        result = await client.call_tool("stamp", {"text": "hello"})
        print(result.content)
        # [TextContent(text='[stamped] hello')]
