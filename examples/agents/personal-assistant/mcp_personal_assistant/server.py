"""
Personal Assistant Agent - MCP Server
This agent acts as a personal assistant that can connect to other agents like the Project Analyst.
"""

import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional

import anyio
import click
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.context import RequestContext
from mcp.types import ElicitRequestParams, ElicitResult, TextContent
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp_server = FastMCP(name="Personal Assistant")

# Server connections
server_sessions: Dict[str, ClientSession] = {}
exit_stack = AsyncExitStack()


class ProjectRequest(BaseModel):
    """Schema for project analysis requests."""

    project_name: str
    issue_count: int = Field(default=5)


def _extract_project_name(message: str) -> Optional[str]:
    """Extract a project name from a message."""
    words = message.lower().split()
    # Simply find the word after "project"
    for i, word in enumerate(words):
        if word == "project" and i < len(words) - 1:
            return words[i + 1]
    return None


async def _get_project_analysis(
    ctx: Context, project_name: str, issue_count: int = 5
) -> Optional[str]:
    """Get project analysis from the analyst service."""
    if "project-analyst" not in server_sessions:
        return None

    try:
        await ctx.info(f"Calling Project Analyst for {project_name}")
        result = await server_sessions["project-analyst"].call_tool(
            "analyze_issues",
            {"project_name": project_name, "issue_count": issue_count},
        )

        # Extract text content from the result
        content = result.content
        if content and isinstance(content[0], TextContent):
            return content[0].text
        return None
    except Exception as e:
        await ctx.error(f"Error calling Project Analyst: {str(e)}")
        return None


@mcp_server.tool(description="Chat with your personal assistant")
async def chat(message: str, ctx: Context) -> str:
    """Have a conversation with your personal assistant."""
    await ctx.info(f"Processing message: {message}")

    # Check if the message is asking about projects
    if any(
        word in message.lower() for word in ["project", "issues", "tasks", "priority"]
    ):
        # Try to extract project name or get it through elicitation
        project_name = _extract_project_name(message)
        issue_count = 5

        if not project_name:
            # Ask for project name through elicitation using Pydantic model
            try:
                response = await ctx.elicit(
                    message="Which project would you like information about?",
                    requestedSchema=ProjectRequest.model_json_schema(),
                )
                project_request = ProjectRequest.model_validate(response)
                project_name = project_request.project_name
                issue_count = project_request.issue_count
            except Exception as e:
                await ctx.error(f"Error during elicitation: {str(e)}")
                return "I encountered an issue while trying to get project information."

        # Get project analysis if we have a project name
        if project_name:
            analysis = await _get_project_analysis(ctx, project_name, issue_count)
            if analysis:
                return f"Here's my analysis of project '{project_name}':\n\n{analysis}"
            return f"I couldn't get information about project '{project_name}'."

    # Default response
    return "I'm your personal assistant. How can I help you today?"


@mcp_server.tool(description="List available connected services")
async def list_services(ctx: Context) -> str:
    """List all available services/agents this assistant can connect to."""
    await ctx.info("Listing available services")
    services = list(server_sessions.keys())

    if not services:
        return "No services are currently connected."

    return (
        f"Connected services:\n{chr(10).join(f'- {service}' for service in services)}"
    )


async def setup_server_connections(config_path: str) -> None:
    """Setup connections to other MCP servers."""
    # Load server config
    with open(config_path, "r") as f:
        servers_config = json.load(f)

    # Connect to each server
    for name, config in servers_config["mcpServers"].items():
        try:
            logger.info(f"Connecting to MCP server: {name}")

            # Create environment with any specified vars
            env = os.environ.copy()
            if config.get("env"):
                env.update(config["env"])

            # Setup connection parameters
            server_params = StdioServerParameters(
                command=config["command"],
                args=config.get("args", []),
                env=env,
            )

            # Create stdio transport
            stdio_transport = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport

            # Create elicitation callback - this is a key part of the demo!
            async def custom_elicitation_callback(
                context: RequestContext["ClientSession", Any],  # noqa: F821
                params: ElicitRequestParams,
            ) -> ElicitResult:
                # The agent can:
                # 1. Forward the elicitation to the user (CLI)
                # 2. Handle it internally if it has the information
                # 3. Reject the request
                logger.info(f"Received elicitation request: {params.message}")
                # Agent can handle the elicitation internally and can return a value
                if "proceed" in params.requestedSchema.get("properties", {}).keys():
                    return ElicitResult(content={"proceed": True})
                else:
                    # Alternatively, we can ask the user for input
                    # and return the response
                    raise ValueError("Elicitation not supported for this request.")

            # Create and initialize session
            session = await exit_stack.enter_async_context(
                ClientSession(
                    read, write, elicitation_callback=custom_elicitation_callback
                )
            )
            await session.initialize()

            server_sessions[name] = session
            logger.info(f"Connected to MCP server: {name}")

        except Exception as e:
            logger.error(f"Failed to connect to MCP server {name}: {e}")


async def run_server_with_connections(config_path: str) -> None:
    """Run the personal assistant server with connections to other servers."""
    try:
        await setup_server_connections(config_path)
        logger.info("Starting Personal Assistant MCP server...")
        await mcp_server.run_stdio_async()
    finally:
        await exit_stack.aclose()


@click.command()
@click.option("--config", default=None, help="Path to servers configuration JSON file")
@click.option(
    "--log-level",
    default="INFO",
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
def main(config: Optional[str] = None, log_level: str = "INFO") -> int:
    """Run the Personal Assistant agent."""
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Use provided config or default
    config_path = config or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "servers_config.json"
    )

    # Run the server with connections
    anyio.run(run_server_with_connections, config_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
