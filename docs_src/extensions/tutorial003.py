from collections.abc import Sequence
from typing import Any

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
