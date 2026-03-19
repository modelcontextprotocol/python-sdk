"""Multi-tenant MCP server example.

Demonstrates how to register tenant-scoped tools, resources, and prompts
so that each tenant sees only their own items. Tenant identity is
determined by the ``tenant_id`` field on the OAuth ``AccessToken`` and
propagated automatically through the request context.

In this example, "acme" is an analytics company with data tools, while
"globex" is a content company with publishing tools. Each tenant has
completely different capabilities — they share nothing.

NOTE: This example uses a simple in-memory token verifier for
demonstration purposes. In production, integrate with your OAuth
provider to populate ``AccessToken.tenant_id`` from your auth system.
"""

import logging

import click
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.prompts.base import Prompt
from mcp.server.mcpserver.resources.types import FunctionResource
from mcp.server.mcpserver.server import MCPServer

logger = logging.getLogger(__name__)


def create_server() -> MCPServer:
    """Create an MCPServer with tenant-scoped tools, resources, and prompts.

    Each tenant has completely different tools, resources, and prompts.
    Acme is an analytics company; Globex is a content company.
    """

    server = MCPServer("multi-tenant-demo")

    # -- Tenant "acme" (analytics company) ---------------------------------

    def run_query(sql: str) -> str:
        """Execute an analytics query."""
        return f"Query result for: {sql} (3 rows returned)"

    def generate_report(metric: str, period: str) -> str:
        """Generate an analytics report."""
        return f"Report: {metric} over {period} — trend is up 12%"

    server.add_tool(run_query, tenant_id="acme")
    server.add_tool(generate_report, tenant_id="acme")

    server.add_resource(
        FunctionResource(
            uri="data://schema",
            name="database-schema",
            fn=lambda: "tables: users, events, metrics",
        ),
        tenant_id="acme",
    )

    async def acme_analyst_prompt() -> str:
        return "You are a data analyst. Help the user write SQL queries and interpret results."

    server.add_prompt(Prompt.from_function(acme_analyst_prompt, name="analyst"), tenant_id="acme")

    # -- Tenant "globex" (content company) ---------------------------------

    def publish_article(title: str, body: str) -> str:
        """Publish an article to the CMS."""
        return f"Published: '{title}' ({len(body)} chars)"

    def check_seo(url: str) -> str:
        """Check SEO score for a URL."""
        return f"SEO score for {url}: 87/100 — missing meta description"

    server.add_tool(publish_article, tenant_id="globex")
    server.add_tool(check_seo, tenant_id="globex")

    server.add_resource(
        FunctionResource(
            uri="content://style-guide",
            name="style-guide",
            fn=lambda: "Tone: professional but approachable. Max paragraph length: 3 sentences.",
        ),
        tenant_id="globex",
    )

    async def globex_editor_prompt() -> str:
        return "You are a content editor. Help the user write and publish articles."

    server.add_prompt(Prompt.from_function(globex_editor_prompt, name="editor"), tenant_id="globex")

    # -- Shared "whoami" tool (registered per tenant) ----------------------
    # There is no global scope fallback — tools must be registered under
    # each tenant that needs them.

    def whoami(ctx: Context) -> str:
        """Return the current tenant identity."""
        return f"tenant: {ctx.tenant_id or 'anonymous'}"

    server.add_tool(whoami, name="whoami", tenant_id="acme")
    server.add_tool(whoami, name="whoami", tenant_id="globex")

    return server


@click.command()
@click.option("--port", default=3000, help="Port to listen on")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
def main(port: int, log_level: str) -> int:
    """Run the multi-tenant MCP demo server.

    Acme (analytics) and Globex (content) each have completely different
    tools, resources, and prompts. Neither tenant can see the other's items.
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    server = create_server()
    logger.info(f"Starting multi-tenant MCP server on port {port}")
    server.run(transport="streamable-http", host="127.0.0.1", port=port)
    return 0


if __name__ == "__main__":
    main()  # type: ignore[call-arg]
