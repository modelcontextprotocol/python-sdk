"""
AI Agent that uses MCP client with dynamic tool loading.

This agent demonstrates:
1. Using ClientSessionGroup to connect to MCP servers
2. Dynamic tool loading via ToolListChangedNotification
3. Claude API for intelligent tool selection and execution
4. Real-time logging of tool discovery process
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, TypedDict

import anthropic
from anthropic.types import Message, TextBlock
from dotenv import load_dotenv

from mcp.client.session_group import ClientSessionGroup, StdioServerParameters
from mcp.types import TextContent


class ToolDict(TypedDict, total=False):
    """Type for tool dictionary from gateway result."""

    name: str
    description: str


# Load environment variables from .env file
load_dotenv()

# ANSI color codes
GREEN = "\033[92m"
BLUE = "\033[94m"
RED = "\033[91m"
RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    """Custom formatter that colors log messages with specific patterns."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if "[AGENT]" in formatted:
            formatted = f"{GREEN}{formatted}{RESET}"
        elif "[CONTEXT]" in formatted:
            formatted = f"{RED}{formatted}{RESET}"
        elif "[DISCOVERY]" in formatted:
            formatted = f"{BLUE}{formatted}{RESET}"
        # Commented out MCP coloring for now
        # elif "[MCP]" in formatted or record.name in ("client", "mcp.client.session", "mcp.client.session_group"):
        #     formatted = f"{RED}{formatted}{RESET}"
        return formatted


# Configure detailed logging
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(ColoredFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler],
)

logger = logging.getLogger(__name__)

# Suppress MCP client loggers
logging.getLogger("mcp.client.session").setLevel(logging.WARNING)
logging.getLogger("mcp.client.session_group").setLevel(logging.WARNING)
logging.getLogger("client").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)

# Silence some noisy loggers
logging.getLogger("anthropic").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class ContextWindowTracker:
    """Track actual token usage from Claude API responses in real-time."""

    def __init__(self) -> None:
        self.messages: list[dict[str, int]] = []
        self.total_input: int = 0
        self.total_output: int = 0

    def add_message(self, message: Message) -> None:
        """Record and log token usage immediately."""
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens

        self.messages.append(
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": getattr(message.usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(message.usage, "cache_read_input_tokens", 0),
            }
        )

        # Update running totals
        self.total_input += input_tokens
        self.total_output += output_tokens
        total = self.total_input + self.total_output

        # Log real-time usage
        logger.info(
            "[CONTEXT]  Turn %d - Input: %d | Output: %d | Running Total: %d tokens",
            len(self.messages),
            input_tokens,
            output_tokens,
            total,
        )

    def log_efficiency_report(self) -> None:
        """Log final context window usage report."""
        logger.info("=" * 80)
        logger.info("FINAL CONTEXT WINDOW USAGE REPORT")
        logger.info("=" * 80)

        logger.info("[CONTEXT] Total messages: %d", len(self.messages))
        logger.info("[CONTEXT] Total input tokens: %d", self.total_input)
        logger.info("[CONTEXT] Total output tokens: %d", self.total_output)
        logger.info("[CONTEXT] Total tokens: %d", self.total_input + self.total_output)

        logger.info("=" * 80)


class MCPClient:
    """High-level MCP client using our enhanced SDK with progressive discovery.

    This is a proof-of-concept showing how to leverage ClientSessionGroup's
    built-in discovery methods to create a clean, reusable client wrapper.

    Example:
        ```python
        client = MCPClient()
        await client.connect_to_server(server_params)

        # Get discovery summary
        summary = await client.get_discovery_summary()

        # Call a tool and refresh
        await client.call_tool("math", {})
        await client.refresh_discovery()
        ```
    """

    def __init__(self):
        """Initialize the MCP client with our enhanced SDK."""
        self._session_group = ClientSessionGroup()
        self.tools: dict[str, Any] = {}

    async def connect_to_server(self, server_params: StdioServerParameters) -> None:
        """Connect to an MCP server.

        Args:
            server_params: StdioServerParameters with server command/args
        """
        try:
            await self._session_group.__aenter__()
            await self._session_group.connect_to_server(server_params)
            logger.info("[MCP]  Connected to server")
            await self.refresh_discovery()
        except Exception as e:
            logger.error("[MCP] ✗ Failed to connect: %s", e)
            raise

    async def refresh_discovery(self) -> None:
        """Refresh tools, prompts, and resources from the server."""
        summary = await self.get_discovery_summary()
        self.tools = self._session_group.tools
        logger.info(
            "[MCP]  Refreshed: %d gateways + %d executables",
            summary["stats"]["gateway_tools"],
            summary["stats"]["executable_tools"],
        )

    async def get_discovery_summary(self) -> dict[str, Any]:
        """Get a structured summary of available tools and resources.

        Returns:
            Dictionary with gateway_tools, executable_tools, resources, prompts, and stats
        """
        return await self._session_group.get_discovery_summary()

    async def list_gateway_tools(self):
        """Get only gateway tools (for initial minimal context)."""
        return await self._session_group.list_gateway_tools()

    async def list_executable_tools(self):
        """Get only executable (non-gateway) tools."""
        return await self._session_group.list_executable_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Execute a tool and return the result.

        After calling a gateway tool, call refresh_discovery() to get updated tools.

        Args:
            name: Tool name
            arguments: Tool arguments
        """
        return await self._session_group.call_tool(name, arguments)

    @staticmethod
    def is_gateway_tool(tool: Any) -> bool:
        """Check if a tool is a gateway tool."""
        return ClientSessionGroup.is_gateway_tool(tool)

    @property
    def prompts(self) -> dict[str, Any]:
        """Get available prompts from the session group."""
        return self._session_group.prompts

    @property
    def resources(self) -> dict[str, Any]:
        """Get available resources from the session group."""
        return self._session_group.resources

    def get_first_session(self) -> Any:
        """Get the first active session from the session group.

        Returns:
            The first ClientSession object, or None if no sessions are active
        """
        sessions = self._session_group._sessions  # type: ignore[reportProtectedAccess]
        if sessions:
            return list(sessions.keys())[0]
        return None

    async def cleanup(self) -> None:
        """Clean up resources."""
        await self._session_group.__aexit__(None, None, None)


class ProgressiveDiscoveryAgent:
    """AI agent that uses dynamic tool loading with Claude.

    This demonstrates how to combine MCPClient with Claude for intelligent
    tool selection and progressive discovery.
    """

    def __init__(self):
        self.mcp_client: MCPClient | None = None
        self.claude_client = anthropic.Anthropic()
        self.tools_loaded = False
        self.available_tools: dict[str, Any] = {}
        self.context_tracker = ContextWindowTracker()

    async def initialize(self):
        """Initialize connection to MCP server using our enhanced MCPClient."""
        logger.info("=" * 80)
        logger.info("INITIALIZING PROGRESSIVE DISCOVERY AGENT")
        logger.info("=" * 80)

        # Create our high-level MCP client wrapper
        self.mcp_client = MCPClient()

        # Connect to the discovery server via stdio
        logger.info("\n[AGENT] Connecting to MCP server...")
        discovery_dir = os.path.dirname(os.path.abspath(__file__))
        server_params = StdioServerParameters(
            command="uv",
            args=["run", "progressive_discovery_server.py"],
            cwd=discovery_dir,
        )

        try:
            # Connect using the MCPClient (handles all discovery internally)
            await self.mcp_client.connect_to_server(server_params)
            logger.info("[AGENT] ✓ Connected to MCP server")
            logger.info("[AGENT] ✓ Session established and ready")

            # Get initial tool list (should be gateway tools only)
            await self._refresh_tools()
            logger.info("[AGENT] ✓ Initial tool list loaded (gateway tools)")

            # Discover other primitives (prompts and resources)
            logger.info("\n[AGENT] Discovering other MCP primitives...")
            await self._discover_prompts()
            await self._discover_resources()
            logger.info("[AGENT] ✓ All primitives discovered")
        except Exception as e:
            logger.error("[AGENT] ✗ Failed to connect: %s", e)
            raise

    async def _refresh_tools(self):
        """Refresh the available tools from the server using MCPClient."""
        if not self.mcp_client:
            raise RuntimeError("MCP client not initialized")

        logger.info("[AGENT] Refreshing available tools...")

        # Use the MCPClient's discovery methods with automatic refresh
        await self.mcp_client.refresh_discovery()
        summary = await self.mcp_client.get_discovery_summary()

        self.available_tools = self.mcp_client.tools
        logger.info("[AGENT] ✓ Tools refreshed")

        # Log discovery summary with clear distinction
        logger.info("[DISCOVERY] Tool Status:")
        gateways = summary["gateway_tools"]
        executable = summary["executable_tools"]

        if gateways:
            logger.info("[DISCOVERY]    Tool Groups (gateways):")
            for tool_info in gateways:
                desc = tool_info["description"]
                desc_short = (desc[:50] + "...") if len(desc) > 50 else desc
                logger.info("[DISCOVERY]      - %s (%s)", tool_info["name"], desc_short)

        if executable:
            logger.info("[DISCOVERY]    Regular Executable Tools:")
            for tool_info in executable:
                desc = tool_info["description"]
                desc_short = (desc[:50] + "...") if len(desc) > 50 else desc
                logger.info("[DISCOVERY]      - %s (%s)", tool_info["name"], desc_short)

        logger.info(
            "[DISCOVERY] Total: %d tool groups + %d regular tools = %d",
            summary["stats"]["gateway_tools"],
            summary["stats"]["executable_tools"],
            summary["stats"]["total_tools"],
        )

    async def _discover_prompts(self) -> list[Any]:
        """Discover available prompts from the server."""
        if not self.mcp_client:
            raise RuntimeError("MCP client not initialized")

        try:
            # Get prompts from the underlying session group
            prompts = self.mcp_client.prompts
            if prompts:
                prompt_list = list(prompts.values())
                logger.info(
                    "[DISCOVERY] Found %d prompts: %s",
                    len(prompt_list),
                    ", ".join(p.name for p in prompt_list),
                )
                return prompt_list
        except Exception:
            logger.debug("[DISCOVERY] Prompts not available on this server")
        return []

    async def _discover_resources(self) -> list[Any]:
        """Discover available resources from the server."""
        if not self.mcp_client:
            raise RuntimeError("MCP client not initialized")

        try:
            # Get resources from the underlying session group
            resources = self.mcp_client.resources
            if resources:
                resource_list = list(resources.values())
                logger.info(
                    "[DISCOVERY] Found %d resources: %s",
                    len(resource_list),
                    ", ".join(r.name for r in resource_list),
                )
                return resource_list
        except Exception:
            logger.debug("[DISCOVERY] Resources not available on this server")
        return []

    async def _refresh_prompts(self):
        """Refresh prompts from the MCPClient and log available prompts."""
        if not self.mcp_client:
            return

        try:
            prompts = self.mcp_client.prompts
            if prompts:
                prompt_names = list(prompts.keys())
                logger.info(
                    "[DISCOVERY]  Prompts loaded: %s",
                    ", ".join(prompt_names),
                )
            else:
                logger.info("[DISCOVERY]  No prompts available")
        except Exception as e:
            logger.debug("[DISCOVERY] Could not refresh prompts: %s", e)

    async def _fetch_and_use_prompt(self, prompt_name: str, arguments: dict[str, str] | None = None) -> str:
        """Fetch a prompt from the server and return its content."""
        if not self.mcp_client:
            return ""

        try:
            # Get first session from the underlying session group
            session = self.mcp_client.get_first_session()
            if session:
                logger.info("[DISCOVERY]  Fetching prompt: %s", prompt_name)
                result = await session.get_prompt(prompt_name, arguments or {})

                if result.messages:
                    # Extract text from prompt messages
                    content_parts: list[str] = []
                    for msg in result.messages:
                        if hasattr(msg.content, "text"):
                            content_parts.append(msg.content.text)  # type: ignore
                        else:
                            content_parts.append(str(msg.content))
                    prompt_content = "\n".join(content_parts)
                    logger.info("[DISCOVERY] ✓ Prompt fetched: %s", prompt_name)
                    return prompt_content
        except Exception as e:
            logger.debug("[DISCOVERY] Could not fetch prompt %s: %s", prompt_name, e)

        return ""

    async def _refresh_resources(self):
        """Refresh resources from the MCPClient and log available resources."""
        if not self.mcp_client:
            return

        try:
            resources = self.mcp_client.resources
            if resources:
                resource_names = list(resources.keys())
                logger.info(
                    "[DISCOVERY]  Resources loaded: %s",
                    ", ".join(resource_names),
                )
            else:
                logger.info("[DISCOVERY]  No resources available")
        except Exception as e:
            logger.debug("[DISCOVERY] Could not refresh resources: %s", e)

    async def _fetch_resource_info(self, resource_name: str) -> dict[str, str] | None:
        """Fetch information about a resource from the server.

        Args:
            resource_name: The name/key of the resource to fetch

        Returns:
            Dictionary with resource information (uri, description, etc.) or None if not found
        """
        if not self.mcp_client:
            return None

        try:
            resources = self.mcp_client.resources
            if resource_name in resources:
                resource = resources[resource_name]  # type: ignore
                logger.info("[DISCOVERY]  Found resource: %s", resource_name)
                return {
                    "name": resource.name,  # type: ignore
                    "description": resource.description,  # type: ignore
                    "uri": str(resource.uri),  # type: ignore
                    "mimeType": resource.mimeType if hasattr(resource, "mimeType") else "text/plain",  # type: ignore
                }
        except Exception as e:
            logger.debug("[DISCOVERY] Could not fetch resource info for %s: %s", resource_name, e)

        return None

    async def _read_resource(self, uri: str) -> str | None:
        """Read the content of a resource by URI.

        Args:
            uri: The URI of the resource to read

        Returns:
            The resource content as a string, or None if not found
        """
        if not self.mcp_client:
            return None

        try:
            # Get first session from the underlying session group
            session = self.mcp_client.get_first_session()
            if session:
                logger.info("[DISCOVERY]  Reading resource: %s", uri)
                result = await session.read_resource(uri)  # type: ignore

                # Extract content from result
                if result.contents and len(result.contents) > 0:  # type: ignore
                    content_block = result.contents[0]  # type: ignore
                    # ReadResourceContents has a 'content' attribute
                    if hasattr(content_block, "content"):
                        logger.info("[DISCOVERY] ✓ Resource read successfully: %s", uri)
                        return str(content_block.content)  # type: ignore
                    elif hasattr(content_block, "text"):
                        # Fallback for TextResourceContents which has 'text'
                        logger.info("[DISCOVERY] ✓ Resource read successfully: %s", uri)
                        return content_block.text  # type: ignore
                    else:
                        return str(content_block)
        except Exception as e:
            logger.debug("[DISCOVERY] Could not read resource %s: %s", uri, e)

        return None

    def _is_gateway_tool(self, tool_name: str) -> bool:
        """Check if a tool is a gateway tool by examining its schema metadata.

        Gateway tools are explicitly marked with "x-gateway": true in their
        inputSchema. This is set by the server when creating gateway tools.

        Args:
            tool_name: Name of the tool to check

        Returns:
            True if the tool is a gateway tool, False otherwise
        """
        if tool_name not in self.available_tools:
            return False

        tool = self.available_tools[tool_name]
        # Use the MCPClient's built-in method for consistent gateway detection
        return MCPClient.is_gateway_tool(tool)

    def _convert_tool_to_api_format(self, tool: Any) -> dict[str, Any]:
        """Convert MCP Tool to Claude API tool format."""
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema or {},
        }

    async def _process_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Execute a tool call through the MCP server."""
        if not self.mcp_client:
            raise RuntimeError("MCP client not initialized")

        logger.info(
            "\033[95m\n[AGENT] Calling tool: %s with args: %s\033[0m",
            tool_name,
            json.dumps(tool_input),
        )

        try:
            # Call the tool through MCPClient with a timeout
            result = await asyncio.wait_for(self.mcp_client.call_tool(tool_name, tool_input), timeout=5.0)

            # Extract text content from result
            if result.content and len(result.content) > 0:
                content_block = result.content[0]
                if isinstance(content_block, TextContent):
                    # Check if this is a gateway tool by examining its schema
                    # Gateway tools have empty inputSchema (no parameters)
                    is_gateway = self._is_gateway_tool(tool_name)

                    if is_gateway:
                        # Format gateway tool results nicely
                        formatted_result = self._format_gateway_result(content_block.text)
                        logger.info("[AGENT] ✓ Gateway result: %s", formatted_result)
                    else:
                        # Truncate regular tool results for logging
                        logger.info(
                            "[AGENT] ✓ Executed result: %s",
                            content_block.text[:200] if len(content_block.text) > 200 else content_block.text,
                        )
                    return content_block.text
            return str(result)
        except asyncio.TimeoutError:
            logger.warning("[AGENT]  Tool call timed out, returning empty result")
            return ""
        except Exception as e:
            logger.error("[AGENT]  Tool execution failed: %s", e)
            raise

    def _format_gateway_result(self, result_text: str) -> str:
        """Format gateway tool result for clean logging on a single line."""
        try:
            # Try to parse as JSON (gateway tools return JSON with tools list)
            parsed: Any = json.loads(result_text)  # type: ignore

            # Helper to extract tools from dict
            if isinstance(parsed, dict) and "tools" in parsed:
                tools_list = parsed.get("tools", [])  # type: ignore
            elif isinstance(parsed, list):
                tools_list = parsed  # type: ignore
            else:
                return "No executable tools found yet"

            # Build tool strings
            if not isinstance(tools_list, list) or len(tools_list) == 0:  # type: ignore
                return "No executable tools found yet"

            tool_strs: list[str] = []
            for tool_item in tools_list:  # type: ignore
                if isinstance(tool_item, dict):
                    name = str(tool_item.get("name", "unknown"))  # type: ignore
                    desc = str(tool_item.get("description", ""))  # type: ignore
                    desc_clean = " ".join(desc.split())
                    tool_strs.append(f"{name} ({desc_clean})")

            if tool_strs:
                return f"Available tools: {', '.join(tool_strs)}"
            return "No executable tools found yet"
        except json.JSONDecodeError:
            # If not JSON, return as-is
            if not result_text.strip():
                return "No executable tools found yet"
            return result_text

    async def chat(self, user_message: str) -> str:
        """Have a multi-turn conversation with Claude using tools."""
        if not self.mcp_client:
            raise RuntimeError("Not initialized")

        logger.info("\n" + "=" * 80)
        logger.info("USER: %s", user_message)
        logger.info("=" * 80)

        messages: list[dict[str, Any]] = []

        # Get current available tools and resources
        await self._refresh_tools()
        api_tools = [self._convert_tool_to_api_format(tool) for tool in self.available_tools.values()]

        # Organize for logging
        gateway_names = [t["name"] for t in api_tools if self._is_gateway_tool(t["name"])]
        regular_names = [t["name"] for t in api_tools if not self._is_gateway_tool(t["name"])]

        logger.info("[DISCOVERY] Claude Context:")
        if gateway_names:
            logger.info("[DISCOVERY]    Gateway tools to explore: %s", ", ".join(gateway_names))
        if regular_names:
            logger.info("[DISCOVERY]    Direct tools available: %s", ", ".join(regular_names))

        # Inject direct resources at the start of conversation
        direct_resources = self.mcp_client.resources if self.mcp_client else {}  # type: ignore
        if direct_resources:
            logger.info("[DISCOVERY] 📦 Injecting direct resources into conversation...")
            resource_contents: list[str] = []
            for resource_name in direct_resources.keys():
                resource_info = await self._fetch_resource_info(resource_name)
                if resource_info:
                    uri = resource_info["uri"]
                    # Try to read the resource content
                    content = await self._read_resource(uri)
                    if content:
                        resource_contents.append(f"[RESOURCE: {resource_info['name']}]\n{content}")
                    else:
                        resource_contents.append(
                            f"[RESOURCE: {resource_info['name']}]\n{resource_info['description']}\nURI: {uri}"
                        )
                    logger.info(
                        "[DISCOVERY] ✓ Loaded resource: %s from %s",
                        resource_info["name"],
                        uri,
                    )

            if resource_contents:
                resource_context = "[AVAILABLE RESOURCES]\n\n" + "\n\n".join(resource_contents)
                messages.append(
                    {
                        "role": "user",
                        "content": resource_context,
                    }
                )
                logger.info("[DISCOVERY] ✓ Injected %d initial resources into conversation", len(resource_contents))

        # Add user message after resource context
        messages.append({"role": "user", "content": user_message})

        # Multi-turn loop for tool use
        while True:
            logger.info("\n[AGENT] Sending request to Claude...")
            kwargs: dict[str, Any] = {
                "model": "claude-opus-4-1-20250805",
                "max_tokens": 4096,
                "messages": messages,  # type: ignore
            }
            if api_tools:
                kwargs["tools"] = api_tools  # type: ignore
            response: Any = self.claude_client.messages.create(**kwargs)  # type: ignore

            # Track context window usage
            if isinstance(response, Message):
                self.context_tracker.add_message(response)

            logger.info(  # type: ignore
                "[AGENT] Claude response - stop_reason: %s | Tokens: input=%d, output=%d, total=%d",
                response.stop_reason,  # type: ignore
                response.usage.input_tokens,  # type: ignore
                response.usage.output_tokens,  # type: ignore
                response.usage.input_tokens + response.usage.output_tokens,  # type: ignore
            )

            # Check if Claude wants to use tools
            if response.stop_reason == "tool_use":  # type: ignore
                # Collect all tool use blocks and process them
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]  # type: ignore
                tool_results = []

                for block in tool_use_blocks:  # type: ignore
                    tool_name: str = block.name  # type: ignore
                    tool_input: dict[str, Any] = block.input  # type: ignore

                    # Check if this is a gateway tool
                    is_gateway = self._is_gateway_tool(tool_name)  # type: ignore

                    # Execute the tool
                    tool_result = await self._process_tool_call(tool_name, tool_input)  # type: ignore

                    # If it was a gateway tool, refresh our local state
                    # (Client automatically handles background refresh of caches)
                    if is_gateway:
                        logger.info("[DISCOVERY] Gateway tool executed, refreshing local state...")
                        await self._refresh_tools()
                        await self._refresh_prompts()
                        await self._refresh_resources()

                        # Rebuild API tools with newly loaded tools
                        api_tools = [self._convert_tool_to_api_format(tool) for tool in self.available_tools.values()]

                        # Separate gateway tools from executable tools
                        gateway_tools = [t["name"] for t in api_tools if self._is_gateway_tool(t["name"])]
                        executable_tools = [t["name"] for t in api_tools if not self._is_gateway_tool(t["name"])]

                        logger.info(
                            "[DISCOVERY] ✓ Discovery state updated! Gateway tools: %s | Executable tools: %s",
                            ", ".join(gateway_tools) if gateway_tools else "none",
                            ", ".join(executable_tools) if executable_tools else "none",
                        )

                        # Fetch and inject relevant prompts
                        available_prompts = self.mcp_client.prompts if self.mcp_client else {}  # type: ignore
                        if available_prompts:
                            logger.info("[DISCOVERY]  Fetching and injecting prompts into conversation...")
                            for prompt_name in available_prompts.keys():
                                # Fetch the prompt
                                prompt_content = await self._fetch_and_use_prompt(prompt_name)
                                if prompt_content:
                                    # Inject prompt as a system message to guide Claude
                                    messages.append(
                                        {
                                            "role": "user",
                                            "content": f"[PROMPT GUIDE]\n{prompt_content}",
                                        }
                                    )
                                    logger.info("[DISCOVERY] ✓ Injected prompt: %s into conversation", prompt_name)

                        # Fetch and inject available resources
                        available_resources = self.mcp_client.resources if self.mcp_client else {}  # type: ignore
                        if available_resources:
                            logger.info("[DISCOVERY]  Fetching and injecting resources into conversation...")
                            loaded_resources: list[str] = []
                            for resource_name in available_resources.keys():
                                # Fetch resource information
                                resource_info = await self._fetch_resource_info(resource_name)
                                if resource_info:
                                    uri = resource_info["uri"]
                                    # Try to read the resource content
                                    content = await self._read_resource(uri)
                                    if content:
                                        loaded_resources.append(f"[RESOURCE: {resource_info['name']}]\n{content}")
                                    else:
                                        loaded_resources.append(
                                            f"[RESOURCE: {resource_info['name']}]\n{resource_info['description']}\nURI: {uri}"
                                        )
                                    logger.info(
                                        "[DISCOVERY] ✓ Loaded resource: %s from %s",
                                        resource_info["name"],
                                        uri,
                                    )

                            if loaded_resources:
                                # Inject all resources with their content
                                resource_context = "[AVAILABLE RESOURCES]\n\n" + "\n\n".join(loaded_resources)
                                messages.append(
                                    {
                                        "role": "user",
                                        "content": resource_context,
                                    }
                                )
                                logger.info(
                                    "[DISCOVERY] ✓ Injected %d resources into conversation", len(loaded_resources)
                                )

                    # Collect tool result
                    tool_results.append(  # type: ignore
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,  # type: ignore
                            "content": tool_result,
                        }
                    )

                # Add assistant response and all tool results to messages
                messages.append({"role": "assistant", "content": response.content})  # type: ignore
                messages.append({"role": "user", "content": tool_results})
            else:
                # Claude is done - extract final response
                final_response = ""
                for block in response.content:  # type: ignore
                    if isinstance(block, TextBlock):
                        final_response += block.text

                logger.info("\n[AGENT] ✓ Final response:")
                logger.info("-" * 80)
                logger.info(final_response)
                logger.info("-" * 80)

                return final_response

    async def run_test_scenarios(self):
        """Run test scenario demonstrating prompt usage and tool group traversal."""
        test_question = "whats the weather like right now in my location, after you figured that out, what is 25 * 5"

        try:
            logger.info("\n" + "=" * 80)
            logger.info("TEST SCENARIO: PROMPT USAGE WITH TOOL GROUP TRAVERSAL")
            logger.info("=" * 80)
            result = await self.chat(test_question)
            logger.info("[RESULT] %s", result)
        except Exception as e:
            logger.error("Error processing question: %s", e)
            import traceback

            traceback.print_exc()
        logger.info("\n")

    async def close(self):
        """Clean up resources."""
        if self.mcp_client:
            await self.mcp_client.cleanup()
            logger.info("[AGENT] Connection closed")


async def main():
    """Main entry point."""
    agent = ProgressiveDiscoveryAgent()

    try:
        await agent.initialize()
        await agent.run_test_scenarios()
    finally:
        # Log context window efficiency report
        agent.context_tracker.log_efficiency_report()
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
