"""Server side: generate a Server Card, then write it OR serve it.

One card definition, two publishing paths (exactly what the SDK should make easy):

    # 1. Hand it to the CLI to publish a static file:
    python examples/serve_card.py write ./server-card.json

    # 2. Serve it from the live server at /.well-known/mcp/server-card:
    python examples/serve_card.py serve --port 8000

The card is derived from the MCPServer's own identity metadata via
``server_card_from_implementation`` and points a remote at this server's
streamable-HTTP endpoint.
"""

from __future__ import annotations

import click
import uvicorn
from mcp.server.mcpserver import MCPServer

from mcp_server_card import (
    Repository,
    ServerCard,
    add_server_card_route,
    server_card_from_implementation,
    streamable_http_remote,
    write_server_card,
)

# A normal high-level MCP server with a single tool.
mcp: MCPServer = MCPServer(
    name="dice-roller",
    title="Dice Roller",
    description="Rolls dice for tabletop games.",
    version="1.0.0",
    website_url="https://example.com/dice",
)


@mcp.tool()
def roll(sides: int = 6) -> int:
    """Roll a single die with the given number of sides."""
    return (sides + 1) // 2  # deterministic stand-in so the example stays reproducible


def build_card(public_url: str) -> ServerCard:
    """Build the Server Card for this server, advertising its remote endpoint."""
    return server_card_from_implementation(
        # Card names are reverse-DNS; the server's display name lives in `title`.
        "io.modelcontextprotocol.examples/dice-roller",
        mcp,
        remotes=[streamable_http_remote(f"{public_url}/mcp", supported_protocol_versions=["2025-11-25"])],
        repository=Repository(url="https://github.com/example-org/dice-roller", source="github"),
    )


@click.group()
def cli() -> None:
    """Generate, write, or serve the dice-roller Server Card."""


@cli.command()
@click.argument("path", type=click.Path(dir_okay=False))
@click.option("--public-url", default="https://dice.example.com", help="Public origin used in the card's remote URL.")
def write(path: str, public_url: str) -> None:
    """Generate the card and write it to PATH (static publishing)."""
    out = write_server_card(build_card(public_url), path)
    click.echo(f"Wrote {out}")


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
def serve(host: str, port: int) -> None:
    """Serve the MCP server with its card at /.well-known/mcp/server-card."""
    card = build_card(f"http://{host}:{port}")
    add_server_card_route(mcp, card)  # registers the well-known GET route
    app = mcp.streamable_http_app(stateless_http=True, host=host)
    click.echo(f"Serving card at http://{host}:{port}/.well-known/mcp/server-card")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    cli()
