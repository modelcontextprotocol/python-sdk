"""One tool that rendezvouses with named peers, proving the server dispatches calls concurrently."""

from collections import defaultdict

import anyio

from mcp.server.mcpserver import Context, MCPServer
from stories._hosting import run_server_from_args


def build_server() -> MCPServer:
    mcp = MCPServer("parallel-calls-example")
    # One Event per tag, shared across calls. A handler sets its own tag's event, then waits for every
    # peer's — no call returns until all peers are concurrently in-flight; sequential dispatch would deadlock.
    arrivals: dict[str, anyio.Event] = defaultdict(anyio.Event)

    @mcp.tool()
    async def meet(tag: str, party: list[str], ctx: Context) -> str:
        """Signal arrival as `tag`, block until every tag in `party` has also arrived, then return."""
        arrivals[tag].set()
        for peer in party:
            await arrivals[peer].wait()
        await ctx.report_progress(1.0, total=1.0, message=tag)
        return tag

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
