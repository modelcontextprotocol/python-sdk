"""Prompt server example showing both return styles.

Run from the repository root:
    uv run examples/snippets/servers/prompt_server.py
"""

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts import base

mcp = MCPServer(name="Prompt Server")


@mcp.prompt(title="Code Review")
def review_code(code: str) -> str:
    """Return a single string prompt asking the model to review code."""
    return f"Please review this code and suggest improvements:\n\n{code}"


@mcp.prompt(title="Debug Assistant")
def debug_error(error: str) -> list[base.Message]:
    """Return a multi-turn conversation as a list of messages."""
    return [
        base.UserMessage("I'm seeing this error:"),
        base.UserMessage(error),
        base.AssistantMessage("I'll help debug that. What have you tried so far?"),
    ]


if __name__ == "__main__":
    mcp.run(transport="stdio")
