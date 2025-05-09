"""
SessionGroup concurrently manages multiple MCP session connections.

Tools, resources, and prompts are aggregated across servers. Servers may
be connected to or disconnected from at any point after initialization.

This abstractions can handle naming collisions using a custom user-provided
hook.
"""

import contextlib
from collections.abc import Callable
from datetime import timedelta
from typing import Any, TypeAlias

from pydantic import BaseModel

import mcp
from mcp import types
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError


class SseServerParameters(BaseModel):
    """Parameters for intializing a sse_client."""

    # The endpoint URL.
    url: str

    # Optional headers to include in requests.
    headers: dict[str, Any] | None = None

    # HTTP timeout for regular operations.
    timeout: float = 5

    # Timeout for SSE read operations.
    sse_read_timeout: float = 60 * 5


class StreamableHttpParameters(BaseModel):
    """Parameters for intializing a streamablehttp_client."""

    # The endpoint URL.
    url: str

    # Optional headers to include in requests.
    headers: dict[str, Any] | None = None

    # HTTP timeout for regular operations.
    timeout: timedelta = timedelta(seconds=30)

    # Timeout for SSE read operations.
    sse_read_timeout: timedelta = timedelta(seconds=60 * 5)

    # Close the client session when the transport closes.
    terminate_on_close: bool = True


ServerParameters: TypeAlias = (
    StdioServerParameters | SseServerParameters | StreamableHttpParameters
)


class ClientSessionGroup:
    """Client for managing connections to multiple MCP servers.

    This class is responsible for encapsulating management of server connections.
    It it aggregates tools, resources, and prompts from all connected servers.

    For auxiliary handlers, such as resource subscription, this is delegated to
    the client and can be accessed via the session. For example:
      mcp_session_group.get_session("server_name").subscribe_to_resource(...)
    """

    class _ComponentNames(BaseModel):
        """Used for reverse index to find components."""

        prompts: set[str] = set()
        resources: set[str] = set()
        tools: set[str] = set()

    # Standard MCP components.
    _prompts: dict[str, types.Prompt]
    _resources: dict[str, types.Resource]
    _tools: dict[str, types.Tool]

    # Client-server connection management.
    _sessions: dict[mcp.ClientSession, _ComponentNames]
    _tool_to_session: dict[str, mcp.ClientSession]
    _exit_stack: contextlib.AsyncExitStack

    # Optional fn consuming (component_name, serverInfo) for custom names.
    # This is provide a means to mitigate naming conflicts across servers.
    # Example: (tool_name, serverInfo) => "{result.serverInfo.name}.{tool_name}"
    _ComponentNameHook: TypeAlias = Callable[[str, types.Implementation], str]
    _component_name_hook: _ComponentNameHook | None

    def __init__(
        self,
        exit_stack: contextlib.AsyncExitStack = contextlib.AsyncExitStack(),
        component_name_hook: _ComponentNameHook | None = None,
    ) -> None:
        """Initializes the MCP client."""

        self._tools = {}
        self._resources = {}
        self._prompts = {}

        self._sessions = {}
        self._tool_to_session = {}
        self._exit_stack = exit_stack
        self._component_name_hook = component_name_hook

    @property
    def prompts(self) -> dict[str, types.Prompt]:
        """Returns the prompts as a dictionary of names to prompts."""
        return self._prompts

    @property
    def resources(self) -> dict[str, types.Resource]:
        """Returns the resources as a dictionary of names to resources."""
        return self._resources

    @property
    def tools(self) -> dict[str, types.Tool]:
        """Returns the tools as a dictionary of names to tools."""
        return self._tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> types.CallToolResult:
        """Executes a tool given its name and arguments."""
        session = self._tool_to_session[name]
        return await session.call_tool(name, args)

    def disconnect_from_server(self, session: mcp.ClientSession) -> None:
        """Disconnects from a single MCP server."""

        if session not in self._sessions:
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message="Provided session is not being managed.",
                )
            )
        component_names = self._sessions[session]

        # Remove prompts associated with the session.
        for name in component_names.prompts:
            del self._prompts[name]

        # Remove resources associated with the session.
        for name in component_names.resources:
            del self._resources[name]

        # Remove tools associated with the session.
        for name in component_names.tools:
            del self._tools[name]

        del self._sessions[session]

    async def connect_to_server(
        self,
        server_params: ServerParameters,
    ) -> mcp.ClientSession:
        """Connects to a single MCP server."""

        # Establish server connection and create session.
        server_info, session = await self._establish_session(server_params)

        # Create a reverse index so we can find all prompts, resources, and
        # tools belonging to this session. Used for removing components from
        # the session group via self.disconnect_from_server.
        component_names = self._ComponentNames()

        # Temporary components dicts. We do not want to modify the aggregate
        # lists in case of an intermediate failure.
        prompts_temp: dict[str, types.Prompt] = {}
        resources_temp: dict[str, types.Resource] = {}
        tools_temp: dict[str, types.Tool] = {}
        tool_to_session_temp: dict[str, mcp.ClientSession] = {}

        # Query the server for its prompts and aggregate to list.
        prompts = (await session.list_prompts()).prompts
        for prompt in prompts:
            name = self._component_name(prompt.name, server_info)
            if name in self._prompts:
                raise McpError(
                    types.ErrorData(
                        code=types.INVALID_PARAMS,
                        message=f"{name} already exists in group prompts.",
                    )
                )
            prompts_temp[name] = prompt
            component_names.prompts.add(name)

        # Query the server for its resources and aggregate to list.
        resources = (await session.list_resources()).resources
        for resource in resources:
            name = self._component_name(resource.name, server_info)
            if name in self._resources:
                raise McpError(
                    types.ErrorData(
                        code=types.INVALID_PARAMS,
                        message=f"{name} already exists in group resources.",
                    )
                )
            resources_temp[name] = resource
            component_names.resources.add(name)

        # Query the server for its tools and aggregate to list.
        tools = (await session.list_tools()).tools
        for tool in tools:
            name = self._component_name(tool.name, server_info)
            if name in self._tools:
                raise McpError(
                    types.ErrorData(
                        code=types.INVALID_PARAMS,
                        message=f"{name} already exists in group tools.",
                    )
                )
            tools_temp[name] = tool
            tool_to_session_temp[name] = session
            component_names.tools.add(name)

        # Aggregate components.
        self._sessions[session] = component_names
        self._prompts.update(prompts_temp)
        self._resources.update(resources_temp)
        self._tools.update(tools_temp)
        self._tool_to_session.update(tool_to_session_temp)

        return session

    async def _establish_session(
        self, server_params: ServerParameters
    ) -> tuple[types.Implementation, mcp.ClientSession]:
        """Establish a client session to an MCP server."""

        # Create read and write streams that facilitate io with the server.
        if isinstance(server_params, StdioServerParameters):
            client = mcp.stdio_client(server_params)
            read, write = await self._exit_stack.enter_async_context(client)
        elif isinstance(server_params, SseServerParameters):
            client = sse_client(
                url=server_params.url,
                headers=server_params.headers,
                timeout=server_params.timeout,
                sse_read_timeout=server_params.sse_read_timeout,
            )
            read, write = await self._exit_stack.enter_async_context(client)
        else:
            client = streamablehttp_client(
                url=server_params.url,
                headers=server_params.headers,
                timeout=server_params.timeout,
                sse_read_timeout=server_params.sse_read_timeout,
                terminate_on_close=server_params.terminate_on_close,
            )
            read, write, _ = await self._exit_stack.enter_async_context(client)

        session = await self._exit_stack.enter_async_context(
            mcp.ClientSession(read, write)
        )
        result = await session.initialize()
        return result.serverInfo, session

    def _component_name(self, name: str, server_info: types.Implementation) -> str:
        if self._component_name_hook:
            return self._component_name_hook(name, server_info)
        return name
