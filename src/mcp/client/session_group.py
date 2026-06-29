"""Manage concurrent sessions to multiple MCP servers, aggregating their tools, resources, and prompts."""

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, TypeAlias, overload

import anyio
import httpx
import mcp_types as types
from pydantic import BaseModel, Field
from typing_extensions import Self

import mcp
from mcp.client.session import ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError
from mcp.shared.session import ProgressFnT


class SseServerParameters(BaseModel):
    """Parameters for initializing an sse_client."""

    url: str
    headers: dict[str, Any] | None = None
    # Timeouts in seconds: `timeout` for regular HTTP operations, `sse_read_timeout` for SSE reads.
    timeout: float = 5.0
    sse_read_timeout: float = 300.0


class StreamableHttpParameters(BaseModel):
    """Parameters for initializing a streamable_http_client."""

    url: str
    headers: dict[str, Any] | None = None
    # Timeouts in seconds: `timeout` for regular HTTP operations, `sse_read_timeout` for SSE reads.
    timeout: float = 30.0
    sse_read_timeout: float = 300.0
    # Terminate the server session when the transport closes.
    terminate_on_close: bool = True


ServerParameters: TypeAlias = StdioServerParameters | SseServerParameters | StreamableHttpParameters


# Dataclass rather than pydantic BaseModel: pydantic cannot handle Protocol-typed fields.
@dataclass
class ClientSessionParameters:
    """Parameters for establishing a client session to an MCP server."""

    read_timeout_seconds: float | None = None
    sampling_callback: SamplingFnT | None = None
    elicitation_callback: ElicitationFnT | None = None
    list_roots_callback: ListRootsFnT | None = None
    logging_callback: LoggingFnT | None = None
    message_handler: MessageHandlerFnT | None = None
    client_info: types.Implementation | None = None


class ClientSessionGroup:
    """Manages connections to multiple MCP servers, aggregating their tools, resources, and prompts.

    Auxiliary operations such as resource subscription are performed through the
    individual sessions.

    Example:
        ```python
        name_fn = lambda name, server_info: f"{(server_info.name)}_{name}"
        async with ClientSessionGroup(component_name_hook=name_fn) as group:
            for server_param in server_params:
                await group.connect_to_server(server_param)
            ...
        ```
    """

    class _ComponentNames(BaseModel):
        """Names of the components owned by a single session."""

        prompts: set[str] = Field(default_factory=set)
        resources: set[str] = Field(default_factory=set)
        tools: set[str] = Field(default_factory=set)

    _prompts: dict[str, types.Prompt]
    _resources: dict[str, types.Resource]
    _tools: dict[str, types.Tool]

    _sessions: dict[mcp.ClientSession, _ComponentNames]
    _tool_to_session: dict[str, mcp.ClientSession]
    _exit_stack: contextlib.AsyncExitStack
    _session_exit_stacks: dict[mcp.ClientSession, contextlib.AsyncExitStack]

    # Optional hook mapping (component_name, server_info) to a custom name, to avoid collisions across servers.
    _ComponentNameHook: TypeAlias = Callable[[str, types.Implementation], str]
    _component_name_hook: _ComponentNameHook | None

    def __init__(
        self,
        exit_stack: contextlib.AsyncExitStack | None = None,
        component_name_hook: _ComponentNameHook | None = None,
    ) -> None:
        self._tools = {}
        self._resources = {}
        self._prompts = {}

        self._sessions = {}
        self._tool_to_session = {}
        if exit_stack is None:
            self._exit_stack = contextlib.AsyncExitStack()
            self._owns_exit_stack = True
        else:
            self._exit_stack = exit_stack
            self._owns_exit_stack = False
        self._session_exit_stacks = {}
        self._component_name_hook = component_name_hook

    async def __aenter__(self) -> Self:  # pragma: no cover
        if self._owns_exit_stack:
            await self._exit_stack.__aenter__()
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_val: BaseException | None,
        _exc_tb: TracebackType | None,
    ) -> bool | None:  # pragma: no cover
        if self._owns_exit_stack:
            await self._exit_stack.aclose()

        async with anyio.create_task_group() as tg:
            for exit_stack in self._session_exit_stacks.values():
                tg.start_soon(exit_stack.aclose)

    @property
    def sessions(self) -> list[mcp.ClientSession]:
        """The list of managed sessions."""
        return list(self._sessions.keys())  # pragma: no cover

    @property
    def prompts(self) -> dict[str, types.Prompt]:
        """Prompts aggregated from all servers, keyed by name."""
        return self._prompts

    @property
    def resources(self) -> dict[str, types.Resource]:
        """Resources aggregated from all servers, keyed by name."""
        return self._resources

    @property
    def tools(self) -> dict[str, types.Tool]:
        """Tools aggregated from all servers, keyed by name."""
        return self._tools

    @overload
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: types.RequestParamsMeta | None = None,
        allow_input_required: Literal[False] = False,
    ) -> types.CallToolResult: ...

    @overload
    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: types.RequestParamsMeta | None = None,
        allow_input_required: bool,
    ) -> types.CallToolResult | types.InputRequiredResult: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: float | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        input_responses: types.InputResponses | None = None,
        request_state: str | None = None,
        meta: types.RequestParamsMeta | None = None,
        allow_input_required: bool = False,
    ) -> types.CallToolResult | types.InputRequiredResult:
        """Executes a tool given its name and arguments.

        Raises:
            RuntimeError: If the server returns an `InputRequiredResult` and `allow_input_required` is `False`.
        """
        session = self._tool_to_session[name]
        session_tool_name = self.tools[name].name
        return await session.call_tool(
            session_tool_name,
            arguments=arguments,
            read_timeout_seconds=read_timeout_seconds,
            progress_callback=progress_callback,
            input_responses=input_responses,
            request_state=request_state,
            meta=meta,
            allow_input_required=allow_input_required,
        )

    async def disconnect_from_server(self, session: mcp.ClientSession) -> None:
        """Disconnects from a single MCP server."""

        session_known_for_components = session in self._sessions
        session_known_for_stack = session in self._session_exit_stacks

        if not session_known_for_components and not session_known_for_stack:
            raise MCPError(
                code=types.INVALID_PARAMS,
                message="Provided session is not managed or already disconnected.",
            )

        if session_known_for_components:  # pragma: no branch
            component_names = self._sessions.pop(session)

            for name in component_names.prompts:
                if name in self._prompts:  # pragma: no branch
                    del self._prompts[name]
            for name in component_names.resources:
                if name in self._resources:  # pragma: no branch
                    del self._resources[name]
            for name in component_names.tools:
                if name in self._tools:  # pragma: no branch
                    del self._tools[name]
                if name in self._tool_to_session:  # pragma: no branch
                    del self._tool_to_session[name]

        if session_known_for_stack:
            session_stack_to_close = self._session_exit_stacks.pop(session)  # pragma: no cover
            await session_stack_to_close.aclose()  # pragma: no cover

    async def connect_with_session(
        self, server_info: types.Implementation, session: mcp.ClientSession
    ) -> mcp.ClientSession:
        """Adds an already-established session to the group and aggregates its components."""
        await self._aggregate_components(server_info, session)
        return session

    async def connect_to_server(
        self,
        server_params: ServerParameters,
        session_params: ClientSessionParameters | None = None,
    ) -> mcp.ClientSession:
        """Connects to a single MCP server and aggregates its components."""
        server_info, session = await self._establish_session(server_params, session_params or ClientSessionParameters())
        return await self.connect_with_session(server_info, session)

    async def _establish_session(
        self,
        server_params: ServerParameters,
        session_params: ClientSessionParameters,
    ) -> tuple[types.Implementation, mcp.ClientSession]:
        """Establish a client session to an MCP server."""

        session_stack = contextlib.AsyncExitStack()
        try:
            if isinstance(server_params, StdioServerParameters):
                client = mcp.stdio_client(server_params)
                read, write = await session_stack.enter_async_context(client)
            elif isinstance(server_params, SseServerParameters):
                client = sse_client(
                    url=server_params.url,
                    headers=server_params.headers,
                    timeout=server_params.timeout,
                    sse_read_timeout=server_params.sse_read_timeout,
                )
                read, write = await session_stack.enter_async_context(client)
            else:
                httpx_client = create_mcp_http_client(
                    headers=server_params.headers,
                    timeout=httpx.Timeout(
                        server_params.timeout,
                        read=server_params.sse_read_timeout,
                    ),
                )
                await session_stack.enter_async_context(httpx_client)

                client = streamable_http_client(
                    url=server_params.url,
                    http_client=httpx_client,
                    terminate_on_close=server_params.terminate_on_close,
                )
                read, write = await session_stack.enter_async_context(client)

            session = await session_stack.enter_async_context(
                mcp.ClientSession(
                    read,
                    write,
                    read_timeout_seconds=session_params.read_timeout_seconds,
                    sampling_callback=session_params.sampling_callback,
                    elicitation_callback=session_params.elicitation_callback,
                    list_roots_callback=session_params.list_roots_callback,
                    logging_callback=session_params.logging_callback,
                    message_handler=session_params.message_handler,
                    client_info=session_params.client_info,
                )
            )

            result = await session.initialize()

            # The session stack itself becomes a resource managed by the group's exit stack.
            self._session_exit_stacks[session] = session_stack
            await self._exit_stack.enter_async_context(session_stack)

            return result.server_info, session
        except Exception:  # pragma: no cover
            await session_stack.aclose()
            raise

    async def _aggregate_components(self, server_info: types.Implementation, session: mcp.ClientSession) -> None:
        """Aggregates prompts, resources, and tools from a given session."""

        # Reverse index used by disconnect_from_server to remove this session's components.
        component_names = self._ComponentNames()

        # Stage into temporary dicts so an intermediate failure leaves the group state untouched.
        prompts_temp: dict[str, types.Prompt] = {}
        resources_temp: dict[str, types.Resource] = {}
        tools_temp: dict[str, types.Tool] = {}
        tool_to_session_temp: dict[str, mcp.ClientSession] = {}

        try:
            prompts = (await session.list_prompts()).prompts
            for prompt in prompts:
                name = self._component_name(prompt.name, server_info)
                prompts_temp[name] = prompt
                component_names.prompts.add(name)
        except MCPError as err:  # pragma: no cover
            logging.warning(f"Could not fetch prompts: {err}")

        try:
            resources = (await session.list_resources()).resources
            for resource in resources:
                name = self._component_name(resource.name, server_info)
                resources_temp[name] = resource
                component_names.resources.add(name)
        except MCPError as err:  # pragma: no cover
            logging.warning(f"Could not fetch resources: {err}")

        try:
            tools = (await session.list_tools()).tools
            for tool in tools:
                name = self._component_name(tool.name, server_info)
                tools_temp[name] = tool
                tool_to_session_temp[name] = session
                component_names.tools.add(name)
        except MCPError as err:  # pragma: no cover
            logging.warning(f"Could not fetch tools: {err}")

        if not any((prompts_temp, resources_temp, tools_temp)):
            del self._session_exit_stacks[session]  # pragma: no cover

        matching_prompts = prompts_temp.keys() & self._prompts.keys()
        if matching_prompts:
            raise MCPError(  # pragma: no cover
                code=types.INVALID_PARAMS,
                message=f"{matching_prompts} already exist in group prompts.",
            )
        matching_resources = resources_temp.keys() & self._resources.keys()
        if matching_resources:
            raise MCPError(  # pragma: no cover
                code=types.INVALID_PARAMS,
                message=f"{matching_resources} already exist in group resources.",
            )
        matching_tools = tools_temp.keys() & self._tools.keys()
        if matching_tools:
            raise MCPError(code=types.INVALID_PARAMS, message=f"{matching_tools} already exist in group tools.")

        self._sessions[session] = component_names
        self._prompts.update(prompts_temp)
        self._resources.update(resources_temp)
        self._tools.update(tools_temp)
        self._tool_to_session.update(tool_to_session_temp)

    def _component_name(self, name: str, server_info: types.Implementation) -> str:
        if self._component_name_hook:
            return self._component_name_hook(name, server_info)
        return name
