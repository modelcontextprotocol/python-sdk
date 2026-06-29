from typing import Annotated

from pydantic import Field

from mcp.server import MCPServer

mcp = MCPServer("Code Helper")


@mcp.prompt(title="Code review")
def review_code(
    code: Annotated[str, Field(description="The code to review.")],
    language: Annotated[str, Field(description="The language the code is written in.")] = "python",
) -> str:
    """Review a piece of code."""
    return f"Please review this {language} code:\n\n{code}"
