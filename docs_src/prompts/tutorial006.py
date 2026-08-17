from contextlib import suppress

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.prompts import Prompt

mcp = MCPServer("Code Helper")


@mcp.prompt()
def review_code(code: str) -> str:
    """Review a piece of code."""
    return f"Please review this code:\n\n{code}"


@mcp.tool()
async def save_template(name: str, instruction: str, ctx: Context) -> str:
    """Save an instruction as a prompt the user can pick from the menu."""

    def template(code: str) -> str:
        return f"{instruction}\n\n{code}"

    with suppress(ValueError):  # replace an existing entry of the same name
        mcp.remove_prompt(name)
    mcp.add_prompt(Prompt.from_function(template, name=name, description=instruction))
    await ctx.notify_prompts_changed()
    await ctx.session.send_prompt_list_changed()
    return f"Saved '{name}' to the prompt menu."
