"""Elicitation (handshake-era push style): a tool blocks on user input mid-call."""

from pydantic import BaseModel

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


class Registration(BaseModel):
    username: str
    plan: str | None = None


def build_server() -> MCPServer:
    mcp = MCPServer("legacy-elicitation-example")

    @mcp.tool(description="Register a new account by asking the user for their details.")
    async def register_user(ctx: Context) -> str:
        answer = await ctx.elicit("Please provide your registration details:", Registration)
        if not isinstance(answer, AcceptedElicitation):
            return f"registration {answer.action}"
        return f"registered {answer.data.username} (plan: {answer.data.plan or 'free'})"

    @mcp.tool(description="Link a third-party account by directing the user to a sign-in URL.")
    async def link_account(provider: str, ctx: Context) -> str:
        # elicitation_id must be unique per elicitation, not per provider — scope it to this request.
        elicitation_id = f"link-{provider}-{ctx.request_context.request_id}"
        answer = await ctx.elicit_url(
            f"Sign in to {provider} to link your account",
            url=f"https://example.com/oauth/{provider}/authorize",
            elicitation_id=elicitation_id,
        )
        if answer.action != "accept":
            return f"link {answer.action}"
        # Out-of-band flow finished: tell the client which elicitation completed.
        # The 2-hop `ctx.request_context.*` reach is interim; a later release shortens it.
        await ctx.request_context.session.send_elicit_complete(
            elicitation_id, related_request_id=ctx.request_context.request_id
        )
        return f"linked {provider}"

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
