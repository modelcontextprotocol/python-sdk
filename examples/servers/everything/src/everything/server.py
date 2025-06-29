"""
Everything Server
This example demonstrates the 2025-06-18 protocol features including:
- Tools with progress reporting, logging, elicitation and sampling
- Resource handling (static, dynamic, and templated)
- Prompts with arguments and completions
"""

import json
from typing import Any

from pydantic import AnyUrl, BaseModel, Field
from starlette.requests import Request

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceLink,
    ResourceTemplateReference,
    SamplingMessage,
    TextContent,
)


def create_everything_server() -> FastMCP:
    """Create a comprehensive FastMCP server with all features enabled."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"], allowed_origins=["http://127.0.0.1:*", "http://localhost:*"]
    )
    mcp = FastMCP(name="EverythingServer", transport_security=transport_security)

    # Tool with context for logging and progress
    @mcp.tool(description="A tool that demonstrates logging and progress", title="Progress Tool")
    async def tool_with_progress(message: str, ctx: Context, steps: int = 3) -> str:
        await ctx.info(f"Starting processing of '{message}' with {steps} steps")

        # Send progress notifications
        for i in range(steps):
            progress_value = (i + 1) / steps
            await ctx.report_progress(
                progress=progress_value,
                total=1.0,
                message=f"Processing step {i + 1} of {steps}",
            )
            await ctx.debug(f"Completed step {i + 1}")

        return f"Processed '{message}' in {steps} steps"

    # Simple tool for basic functionality
    @mcp.tool(description="A simple echo tool", title="Echo Tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    # Tool that returns ResourceLinks
    @mcp.tool(description="Lists files and returns resource links", title="List Files Tool")
    def list_files() -> list[ResourceLink]:
        """Returns a list of resource links for files matching the pattern."""

        # Sample file resources
        file_resources = [
            {
                "type": "resource_link",
                "uri": "file:///project/README.md",
                "name": "README.md",
                "mimeType": "text/markdown",
            }
        ]

        result: list[ResourceLink] = [ResourceLink.model_validate(file_json) for file_json in file_resources]
        return result

    # Tool with sampling capability
    @mcp.tool(description="A tool that uses sampling to generate content", title="Sampling Tool")
    async def sampling_tool(prompt: str, ctx: Context) -> str:
        await ctx.info(f"Requesting sampling for prompt: {prompt}")

        # Request sampling from the client
        result = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt))],
            max_tokens=100,
            temperature=0.7,
        )

        await ctx.info(f"Received sampling result from model: {result.model}")
        # Handle different content types
        if result.content.type == "text":
            return f"Sampling result: {result.content.text[:100]}..."
        else:
            return f"Sampling result: {str(result.content)[:100]}..."

    # Tool that sends notifications and logging
    @mcp.tool(description="A tool that demonstrates notifications and logging", title="Notification Tool")
    async def notification_tool(message: str, ctx: Context) -> str:
        # Send different log levels
        await ctx.debug("Debug: Starting notification tool")
        await ctx.info(f"Info: Processing message '{message}'")
        await ctx.warning("Warning: This is a test warning")

        # Send resource change notifications
        await ctx.session.send_resource_list_changed()
        await ctx.session.send_tool_list_changed()

        await ctx.info("Completed notification tool successfully")
        return f"Sent notifications and logs for: {message}"

    # Resource - static
    def get_static_info() -> str:
        return "This is static resource content"

    static_resource = FunctionResource(
        uri=AnyUrl("resource://static/info"),
        name="Static Info",
        title="Static Information",
        description="Static information resource",
        fn=get_static_info,
    )
    mcp.add_resource(static_resource)

    # Resource - dynamic function
    @mcp.resource("resource://dynamic/{category}", title="Dynamic Resource")
    def dynamic_resource(category: str) -> str:
        return f"Dynamic resource content for category: {category}"

    # Resource template
    @mcp.resource("resource://template/{id}/data", title="Template Resource")
    def template_resource(id: str) -> str:
        return f"Template resource data for ID: {id}"

    # Prompt - simple
    @mcp.prompt(description="A simple prompt", title="Simple Prompt")
    def simple_prompt(topic: str) -> str:
        return f"Tell me about {topic}"

    # Prompt - complex with multiple arguments
    @mcp.prompt(description="Complex prompt with context", title="Complex Prompt")
    def complex_prompt(user_query: str, context: str = "general") -> str:
        # Return a single string that incorporates the context
        return f"Context: {context}. Query: {user_query}"

    # Resource template with completion support
    @mcp.resource("github://repos/{owner}/{repo}", title="GitHub Repository")
    def github_repo_resource(owner: str, repo: str) -> str:
        return f"Repository: {owner}/{repo}"

    # Add completion handler for the server
    @mcp.completion()
    async def handle_completion(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        # Handle GitHub repository completion
        if isinstance(ref, ResourceTemplateReference):
            if ref.uri == "github://repos/{owner}/{repo}" and argument.name == "repo":
                if context and context.arguments and context.arguments.get("owner") == "modelcontextprotocol":
                    # Return repos for modelcontextprotocol org
                    return Completion(values=["python-sdk", "typescript-sdk", "specification"], total=3, hasMore=False)
                elif context and context.arguments and context.arguments.get("owner") == "test-org":
                    # Return repos for test-org
                    return Completion(values=["test-repo1", "test-repo2"], total=2, hasMore=False)

        # Handle prompt completions
        if isinstance(ref, PromptReference):
            if ref.name == "complex_prompt" and argument.name == "context":
                # Complete context values
                contexts = ["general", "technical", "business", "academic"]
                return Completion(
                    values=[c for c in contexts if c.startswith(argument.value)], total=None, hasMore=False
                )

        # Default: no completion available
        return Completion(values=[], total=0, hasMore=False)

    # Tool that echoes request headers from context
    @mcp.tool(description="Echo request headers from context", title="Echo Headers")
    def echo_headers(ctx: Context[Any, Any, Request]) -> str:
        """Returns the request headers as JSON."""
        headers_info = {}
        if ctx.request_context.request:
            # Now the type system knows request is a Starlette Request object
            headers_info = dict(ctx.request_context.request.headers)
        return json.dumps(headers_info)

    # Tool that returns full request context
    @mcp.tool(description="Echo request context with custom data", title="Echo Context")
    def echo_context(custom_request_id: str, ctx: Context[Any, Any, Request]) -> str:
        """Returns request context including headers and custom data."""
        context_data = {
            "custom_request_id": custom_request_id,
            "headers": {},
            "method": None,
            "path": None,
        }
        if ctx.request_context.request:
            request = ctx.request_context.request
            context_data["headers"] = dict(request.headers)
            context_data["method"] = request.method
            context_data["path"] = request.url.path
        return json.dumps(context_data)

    # Restaurant booking tool with elicitation
    @mcp.tool(description="Book a table at a restaurant with elicitation", title="Restaurant Booking")
    async def book_restaurant(
        date: str,
        time: str,
        party_size: int,
        ctx: Context,
    ) -> str:
        """Book a table - uses elicitation if requested date is unavailable."""

        class AlternativeDateSchema(BaseModel):
            checkAlternative: bool = Field(description="Would you like to try another date?")
            alternativeDate: str = Field(
                default="2024-12-26",
                description="What date would you prefer? (YYYY-MM-DD)",
            )

        # For demo: assume dates starting with "2024-12-25" are unavailable
        if date.startswith("2024-12-25"):
            # Use elicitation to ask about alternatives
            result = await ctx.elicit(
                message=(
                    f"No tables available for {party_size} people on {date} "
                    f"at {time}. Would you like to check another date?"
                ),
                schema=AlternativeDateSchema,
            )

            if result.action == "accept" and result.data:
                if result.data.checkAlternative:
                    alt_date = result.data.alternativeDate
                    return f"✅ Booked table for {party_size} on {alt_date} at {time}"
                else:
                    return "❌ No booking made"
            elif result.action in ("decline", "cancel"):
                return "❌ Booking cancelled"
            else:
                # Handle case where action is "accept" but data is None
                return "❌ No booking data received"
        else:
            # Available - book directly
            return f"✅ Booked table for {party_size} on {date} at {time}"

    return mcp
