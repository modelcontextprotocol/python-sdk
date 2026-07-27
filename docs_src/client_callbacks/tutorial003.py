from mcp_types import ClientCapabilities, ElicitationCapability, RootsCapability, SamplingCapability
from pydantic import BaseModel

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

mcp = MCPServer("Library")


class CardHolder(BaseModel):
    name: str


@mcp.tool()
async def issue_card(ctx: Context) -> str:
    """Issue a new library card."""
    answer = await ctx.elicit("What name should go on the card?", schema=CardHolder)
    if answer.action == "accept":
        return f"Card issued to {answer.data.name}."
    return "No card issued."


@mcp.tool()
def client_features(ctx: Context) -> list[str]:
    """Which optional features the connected client declared."""
    declared = {
        "elicitation": ClientCapabilities(elicitation=ElicitationCapability()),
        "sampling": ClientCapabilities(sampling=SamplingCapability()),
        "roots": ClientCapabilities(roots=RootsCapability()),
    }
    return [name for name, capability in declared.items() if ctx.session.check_client_capability(capability)]
