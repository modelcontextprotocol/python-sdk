"""Research agent MCP server demonstrating three key features:

1. Collaborative Planning  — set ``collaborative_planning=True`` to present a
   research plan for user approval (via MCP elicitation) before work begins.
2. MCP Support             — configure ``MCP_SERVERS`` (JSON) to connect remote
   MCP servers; their tools are queried as part of the research workflow.
3. Visualizations          — set ``visualization="auto"`` to receive a bar chart
   of key metrics as a base64-encoded ``image/svg+xml`` ImageContent block.
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import click
import mcp.types as types
import uvicorn
from mcp.client.session_group import ClientSessionGroup, SseServerParameters, StreamableHttpParameters
from mcp.client.stdio import StdioServerParameters
from mcp.server.experimental.task_context import ServerTaskContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp_research_agent.visualization import extract_metrics, generate_bar_chart

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Low-level MCP server with task support enabled
# ---------------------------------------------------------------------------

server = Server("research-agent")
server.experimental.enable_tasks()

# Module-level reference to the shared ClientSessionGroup, populated during
# ASGI lifespan so tool handlers can reach connected MCP servers.
_session_group: ClientSessionGroup | None = None


# ---------------------------------------------------------------------------
# MCP server connection helpers
# ---------------------------------------------------------------------------


def _parse_mcp_servers() -> list[StdioServerParameters | SseServerParameters | StreamableHttpParameters]:
    """Parse the ``MCP_SERVERS`` environment variable (JSON array).

    Each element must have a ``"type"`` key (``"stdio"``, ``"sse"``, or
    ``"streamable_http"``) plus the fields required by the corresponding
    parameter class.

    Example::

        MCP_SERVERS='[{"type":"stdio","command":"python","args":["-m","my_server"]}]'
    """
    raw = os.environ.get("MCP_SERVERS", "[]")
    try:
        configs: list[dict[str, Any]] = json.loads(raw)
    except json.JSONDecodeError:
        logger.exception("Failed to parse MCP_SERVERS — expected a JSON array")
        return []

    result: list[StdioServerParameters | SseServerParameters | StreamableHttpParameters] = []
    for cfg in configs:
        server_type = cfg.get("type", "stdio")
        if server_type == "stdio":
            result.append(
                StdioServerParameters(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env=cfg.get("env"),
                )
            )
        elif server_type == "sse":
            result.append(SseServerParameters(url=cfg["url"], headers=cfg.get("headers")))
        elif server_type == "streamable_http":
            result.append(StreamableHttpParameters(url=cfg["url"], headers=cfg.get("headers")))
        else:
            logger.warning("Unknown MCP server type %r — skipping", server_type)
    return result


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Advertise the tools provided by this research agent."""
    return [
        types.Tool(
            name="research",
            description=(
                "Research a topic using LLM sampling and any connected MCP servers. "
                "Supports collaborative planning (user approves the plan before work starts) "
                "and automatic chart generation from extracted metrics."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The research question or topic to investigate.",
                    },
                    "collaborative_planning": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "When true, present a step-by-step research plan for user "
                            "approval before any research is performed."
                        ),
                    },
                    "visualization": {
                        "type": "string",
                        "enum": ["auto", "off"],
                        "default": "off",
                        "description": (
                            "When 'auto', append a bar chart of key numeric findings "
                            "as a base64-encoded SVG ImageContent block."
                        ),
                    },
                },
                "required": ["query"],
            },
            execution=types.ToolExecution(taskSupport=types.TASK_REQUIRED),
        ),
        types.Tool(
            name="list_mcp_tools",
            description="List the tools available from all connected remote MCP servers.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


@server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, Any],
) -> types.CallToolResult | types.CreateTaskResult:
    """Dispatch incoming tool calls to the appropriate handler."""
    if name == "research":
        return await _handle_research(arguments)
    if name == "list_mcp_tools":
        return _handle_list_mcp_tools()
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"Unknown tool: {name}")],
        isError=True,
    )


def _handle_list_mcp_tools() -> types.CallToolResult:
    """Return a summary of tools reachable via connected MCP servers."""
    if _session_group is None or not _session_group.tools:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="No remote MCP servers are connected.")]
        )

    lines = ["Tools available from connected MCP servers:\n"]
    for tool in _session_group.tools.values():
        lines.append(f"  • {tool.name}: {tool.description or '(no description)'}")
    return types.CallToolResult(content=[types.TextContent(type="text", text="\n".join(lines))])


async def _handle_research(arguments: dict[str, Any]) -> types.CreateTaskResult:
    """Implement the ``research`` tool with all three key features."""
    ctx = server.request_context
    ctx.experimental.validate_task_mode(types.TASK_REQUIRED)

    query: str = arguments.get("query", "")
    collaborative_planning: bool = bool(arguments.get("collaborative_planning", False))
    visualization: Literal["auto", "off"] = "auto" if arguments.get("visualization") == "auto" else "off"

    async def work(task: ServerTaskContext) -> types.CallToolResult:
        # ── Feature 1 (part 1): generate a research plan via LLM sampling ──
        await task.update_status("Generating research plan…")
        plan_response = await task.create_message(
            messages=[
                types.SamplingMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Create a concise step-by-step research plan for this query: '{query}'. "
                            "List 3–5 concrete steps. Be brief and specific."
                        ),
                    ),
                )
            ],
            max_tokens=300,
        )
        plan_text: str = (
            plan_response.content.text
            if isinstance(plan_response.content, types.TextContent)
            else f"Research plan for: {query}"
        )

        # ── Feature 1 (part 2): collaborative planning — elicit user approval ──
        if collaborative_planning:
            await task.update_status("Awaiting plan approval…")
            elicit_result = await task.elicit(
                message=(f"Research Plan\n{'─' * 40}\n{plan_text}\n\nApprove this plan to begin research?"),
                requestedSchema={
                    "type": "object",
                    "properties": {
                        "approved": {
                            "type": "boolean",
                            "description": "Set to true to proceed with the research.",
                        },
                        "feedback": {
                            "type": "string",
                            "description": "Optional feedback or requested modifications.",
                        },
                    },
                    "required": ["approved"],
                },
            )

            approved = (
                elicit_result.action == "accept"
                and elicit_result.content is not None
                and bool(elicit_result.content.get("approved"))
            )
            if not approved:
                feedback = (elicit_result.content or {}).get("feedback", "")
                cancel_msg = f"Research cancelled.\nFeedback: {feedback}" if feedback else "Research cancelled by user."
                return types.CallToolResult(content=[types.TextContent(type="text", text=cancel_msg)])

        # ── Feature 2: MCP support — query tools from connected servers ──────
        mcp_context = ""
        if _session_group is not None and _session_group.tools:
            await task.update_status("Querying connected MCP servers…")
            snippets: list[str] = []
            for tool_name in list(_session_group.tools.keys())[:3]:
                try:
                    result = await _session_group.call_tool(tool_name, {})
                    for block in result.content:
                        if isinstance(block, types.TextContent):
                            snippets.append(f"[{tool_name}]: {block.text[:400]}")
                except Exception:
                    logger.exception("Failed to call remote MCP tool %r", tool_name)
            if snippets:
                mcp_context = "\n\nData from connected MCP servers:\n" + "\n".join(snippets)

        # ── Execute the research via LLM sampling ─────────────────────────────
        await task.update_status("Conducting research…")
        research_response = await task.create_message(
            messages=[
                types.SamplingMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Research the following query: '{query}'\n\n"
                            f"Follow this plan:\n{plan_text}"
                            f"{mcp_context}\n\n"
                            "Provide a comprehensive summary with key findings. "
                            "Include specific labelled metrics where possible "
                            "(e.g. 'Market size: $4.5B', 'Growth rate: 12%', 'Users: 1.2M') "
                            "so they can be charted automatically."
                        ),
                    ),
                )
            ],
            max_tokens=1024,
        )
        summary: str = (
            research_response.content.text
            if isinstance(research_response.content, types.TextContent)
            else "Research complete."
        )

        # ── Feature 3: visualizations — SVG bar chart of extracted metrics ────
        content: list[types.ContentBlock] = [types.TextContent(type="text", text=summary)]

        if visualization == "auto":
            await task.update_status("Generating visualization…")
            metrics = extract_metrics(summary)
            if metrics:
                chart_b64 = generate_bar_chart(metrics, title=query[:50])
                content.append(
                    types.ImageContent(
                        type="image",
                        data=chart_b64,
                        mimeType="image/svg+xml",
                    )
                )

        return types.CallToolResult(content=content)

    return await ctx.experimental.run_task(work)


# ---------------------------------------------------------------------------
# ASGI application with lifespan for MCP server connections
# ---------------------------------------------------------------------------


def create_app(session_manager: StreamableHTTPSessionManager) -> Starlette:
    """Build the Starlette ASGI app.

    The lifespan opens a :class:`~mcp.client.session_group.ClientSessionGroup`
    that connects to any MCP servers listed in the ``MCP_SERVERS`` env var,
    making their tools available throughout the request lifetime.
    """

    @asynccontextmanager
    async def app_lifespan(_app: Starlette) -> AsyncIterator[None]:
        global _session_group
        async with ClientSessionGroup() as group:
            _session_group = group
            for params in _parse_mcp_servers():
                try:
                    await group.connect_to_server(params)
                    logger.info("Connected to MCP server: %s", params)
                except Exception:
                    logger.exception("Failed to connect to MCP server: %s", params)

            tool_count = len(group.tools)
            if tool_count:
                logger.info("MCP support: %d remote tool(s) available", tool_count)
            else:
                logger.info("MCP support: no remote servers configured (set MCP_SERVERS)")

            async with session_manager.run():
                yield

        _session_group = None

    return Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=app_lifespan,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


@click.command()
@click.option("--port", default=8000, show_default=True, help="Port to listen on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
def main(port: int, host: str) -> None:
    """Start the research agent MCP server.

    Set the ``MCP_SERVERS`` environment variable (JSON array) to connect remote
    MCP servers and expose their tools during research tasks.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    session_manager = StreamableHTTPSessionManager(app=server)
    starlette_app = create_app(session_manager)
    logger.info("Research agent starting on http://%s:%d/mcp", host, port)
    uvicorn.run(starlette_app, host=host, port=port)
