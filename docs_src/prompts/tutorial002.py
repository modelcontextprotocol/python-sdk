from mcp.server import MCPServer
from mcp.server.mcpserver.prompts.base import AssistantMessage, Message, UserMessage

mcp = MCPServer("Code Helper")


@mcp.prompt()
def review_code(code: str) -> str:
    """Review a piece of code."""
    return f"Please review this code:\n\n{code}"


@mcp.prompt()
def debug_error(error: str) -> list[Message]:
    """Start a debugging conversation."""
    return [
        UserMessage("I'm seeing this error:"),
        UserMessage(error),
        AssistantMessage("I'll help debug that. What have you tried so far?"),
    ]
