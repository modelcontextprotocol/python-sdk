"""Project Analyst Agent - MCP Server

This agent provides tools for analyzing projects and summarizing issues and priorities.
"""

import logging
import sys

import click
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from .mock_data import generate_analysis_report, generate_mock_issues

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize the MCP server
mcp_server = FastMCP(name="Project Analyst Agent")


class ShouldProceed(BaseModel):
    """Schema for elicitation response using Pydantic for validation."""

    proceed: bool


@mcp_server.tool(description="Analyze issues for a project")
async def analyze_issues(
    project_name: str,
    issue_count: int,
    ctx: Context,
) -> str:
    """
    Analyze issues for a project and provide a summary with priorities.

    Args:
        project_name: The name of the project to analyze
        issue_count: Number of issues to analyze
        ctx: The MCP context

    Returns:
        A summary analysis of the project issues and priorities
    """
    await ctx.info(f"Analyzing {issue_count} issues from {project_name}")

    try:
        # Generate mock issues (in a real implementation, this would use an API)
        issues = generate_mock_issues(project_name, issue_count)
        # Check if we need to elicit user input
        if issues:
            response = await ctx.elicit(
                message=f"{len(issues)} issues found. Would you like to proceed?",
                requestedSchema=ShouldProceed.model_json_schema(),
            )
            logger.info(f"Elicitation response: {response}")
            elicit_response = ShouldProceed.model_validate(response)
            if elicit_response.proceed:
                return generate_analysis_report(project_name, issues)

        return "No analysis requested."

    except Exception as e:
        error_message = f"Error analyzing project issues: {str(e)}"
        await ctx.error(error_message)
        return error_message


@click.command()
def main() -> int:
    """Run the MCP server using STDIO transport."""
    logging.info("Starting Project Analyst MCP server...")
    mcp_server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
