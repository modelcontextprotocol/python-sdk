"""
StatefulMCP - A higher-level MCP server with a session-scoped state machine.

This class extends FastMCP and replaces selected public handlers with
state-aware variants with stateful managers based on user-provided states.

It preserves FastMCP's public surface (decorators, run methods, managers),
but injects session awareness by wiring a session-scoped StateMachine into
state-aware tool/resource/prompt managers.

Usage:
    app = StatefulMCP(name="My Stateful Server")

    # Define the state machine via the public DSL
    @app.statebuilder.state("start", is_initial=True)
    def _start(s):
        s.transition("next").on_tool("ping")

    @app.tool()
    async def ping(ctx: Context) -> str:
        return "pong"

    app.run("stdio")
"""

from __future__ import annotations

from typing import Any, Iterable, Literal, Sequence

from pydantic import AnyUrl

from mcp.types import (
    ContentBlock,
    GetPromptResult,
    Prompt as MCPPrompt,
    PromptArgument as MCPPromptArgument,
    Resource as MCPResource,
    Tool as MCPTool,
)

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.state.builder import StateMachineDefinition
from mcp.server.state.machine.state_machine import StateMachine
from mcp.server.state.prompts.state_aware_prompt_manager import (
    StateAwarePromptManager,
)
from mcp.server.state.resources.state_aware_resource_manager import (
    StateAwareResourceManager,
)
from mcp.server.state.tools.state_aware_tool_manager import StateAwareToolManager
from mcp.server.state.types import FastMCPContext


logger = get_logger(f"{__name__}.StatefulMCP")

class StatefulMCP(FastMCP[LifespanResultT]):
    """FastMCP with a session-scoped StateMachine and state-aware managers.

    Overrides FastMCP handlers:
      - list_tools / call_tool
      - list_resources / read_resource
      - list_prompts / get_prompt

    Session scoping:
      State inside the state machine is bound per state for each session.
      If `request_context` is not avaiable the state machine will fall back to a global state.

    Important:
      Define states via `statebuilder`; otherwise no tools/resources/prompts are
      visible and startup validation will fail (e.g., missing initial state).
    """

    def __init__(
            self, 
            global_mode: bool = True, 
            *args: Any, 
            **kwargs: Any
        ) -> None:
        # Parent initialization sets up _mcp_server and native managers
        super().__init__(*args, **kwargs)

        # Public DSL to define
        self._state_definition = StateMachineDefinition(self._tool_manager, self._resource_manager, self._prompt_manager)

        # user defined configs
        self._global_mode = global_mode # runs state machine with shared/global state

        # Session-scoped state machine runtime (built in run())
        self._state_machine: StateMachine | None = None

        # Our state-aware managers (built in run())
        self._stateful_tools: StateAwareToolManager | None = None
        self._stateful_resources: StateAwareResourceManager | None = None
        self._stateful_prompts: StateAwarePromptManager | None = None

    ### Public surface

    @property
    def statebuilder(self) -> StateMachineDefinition:
        """Finite-state machine DSL (public).

        Define states and transitions; the server builds & validates the graph at
        startup. 
        
        Do not call any build method yourself!

        Decorator style::

            @app.statebuilder.state("start", is_initial=True)
            def _(s):
                s.transition("next").on_tool("my_tool")

        Fluent style::

            app.statebuilder
                .define_state("start", is_initial=True)
                .transition("next").on_tool("my_tool")
                .done()
        """
        return self._state_definition

    ### Server lifecycle

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        mount_path: str | None = None,
    ) -> None:
        """Run the server. Build state machine and initialize state-aware managers once."""
        self._build_state_machine_once()
        self._init_stateful_managers_once()
        return super().run(transport=transport, mount_path=mount_path)

    def _build_state_machine_once(self) -> None:
        """Startup-only state machine bootstrap.

        Create a session-scoped machine using a resolver that reads the current
        session id from the request context (falls back to global when none).

        Build & validate the machine once after all user registrations.
        """
        if self._state_machine is not None:
            return

        logger.debug("State machine bootstrap: begin building and validating from DSL")

        internal = self._state_definition._to_internal_builder()  # pyright: ignore[reportPrivateUsage]

        # Pretty important stuff. This resolver is necessary to run a session scoped state machine.
        def _resolve_context() -> FastMCPContext | None:
            try:
                return self.get_context()
            except Exception as e:
                logger.warning("State machine resolver: could not resolve context; falling back to global mode: %s", e)
                return None

        self._state_machine = internal.build(context_resolver=_resolve_context) if self._global_mode \
            else internal.build_session_scoped(context_resolver=_resolve_context)

        logger.debug("State machine bootstrap: build complete and ready")

    def _init_stateful_managers_once(self) -> None:
        """Instantiate state-aware managers once the state machine exists."""
        if self._state_machine is None:
            raise RuntimeError("State machine must be built before initializing stateful managers")
        
        if self._stateful_tools is None:
            logger.debug("State machine wiring: initializing StateAwareToolManager")
            self._stateful_tools = StateAwareToolManager(
                state_machine=self._state_machine,
                tool_manager=self._tool_manager,
            )

        if self._stateful_resources is None:
            logger.debug("State machine wiring: initializing StateAwareResourceManager")
            self._stateful_resources = StateAwareResourceManager(
                state_machine=self._state_machine,
                resource_manager=self._resource_manager,
            )

        if self._stateful_prompts is None:
            logger.debug("State machine wiring: initializing StateAwarePromptManager")
            self._stateful_prompts = StateAwarePromptManager(
                state_machine=self._state_machine,
                prompt_manager=self._prompt_manager,
            )

    ### Overridden FastMCP methods (delegating to state-aware managers)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        """Override FastMCP.

        Execute via the state-aware ToolManager. Access is constrained by the
        session-scoped state machine to tools allowed in the *current state* of the *current session*. 
        
        Forwards the execution context so that tools can access session data.

        Example usage::

            def tool_with_context(ctx: StatefulMCPContext) -> str:
                return ctx.request_context.session.session_id

        Note:
            The context parameter is automatically removed from the signature when listing tools.
        """
        assert self._stateful_tools is not None, "Stateful managers not initialized; call run() first"
        ctx = self.get_context()
        return await self._stateful_tools.call_tool(name, arguments, ctx)


    async def read_resource(self, uri: AnyUrl | str) -> Iterable[ReadResourceContents]:
        """Override FastMCP.

        Read via the state-aware ResourceManager. Access is constrained by the
        session-scoped state machine to resources allowed in the *current state* of the *current session*.
        """
        assert self._stateful_resources is not None, "Stateful managers not initialized; call run() first"
        return await self._stateful_resources.read_resource(uri)


    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        """Override FastMCP.

        Resolve via the state-aware PromptManager. Access is constrained by the
        session-scoped state machine to prompts allowed in the *current state* of the *current session*.
        """
        assert self._stateful_prompts is not None, "Stateful managers not initialized; call run() first"
        return await self._stateful_prompts.get_prompt(name, arguments)


    async def list_tools(self) -> list[MCPTool]:
        """Override FastMCP.

        List via the state-aware ToolManager. Returns only tools permitted by the
        session-scoped state machine for the *current state* of the *current session*.
        """
        assert self._stateful_tools is not None, "Stateful managers not initialized; call run() first"
        tools = self._stateful_tools.list_tools()
        return [
            MCPTool(
                name=tool.name,
                title=tool.title,
                description=tool.description,
                inputSchema=tool.parameters,
                outputSchema=tool.output_schema,
                annotations=tool.annotations,
            )
            for tool in tools
        ]


    async def list_resources(self) -> list[MCPResource]:
        """Override FastMCP.

        List via the state-aware ResourceManager. Returns only resources permitted by
        the session-scoped state machine for the *current state* of the *current session*.
        """
        assert self._stateful_resources is not None, "Stateful managers not initialized; call run() first"
        resources = await self._stateful_resources.list_resources()
        return [
            MCPResource(
                uri=resource.uri,
                name=resource.name or "",
                title=resource.title,
                description=resource.description,
                mimeType=resource.mime_type,
            )
            for resource in resources
        ]


    async def list_prompts(self) -> list[MCPPrompt]:
        """Override FastMCP.

        List via the state-aware PromptManager. Returns only prompts permitted by
        the session-scoped state machine for the *current state* of the *current session*.
        """
        assert self._stateful_prompts is not None, "Stateful managers not initialized; call run() first"
        prompts = self._stateful_prompts.list_prompts()
        return [
            MCPPrompt(
                name=prompt.name,
                title=prompt.title,
                description=prompt.description,
                arguments=[
                    MCPPromptArgument(name=a.name, description=a.description, required=a.required)
                    for a in (prompt.arguments or [])
                ],
            )
            for prompt in prompts
        ]
