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

from typing import Any, Iterable, Literal, Sequence, Generic

import anyio
from pydantic import AnyUrl, PrivateAttr
from starlette.requests import Request

from mcp.server.fastmcp import FastMCP, Context as FastMCPContext
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.lowlevel.server import LifespanResultT
from mcp.server.session import ServerSession, ServerSessionT
from mcp.shared.context import LifespanContextT, RequestContext, RequestT
from mcp.types import (
    ContentBlock,
    GetPromptResult,
    Prompt as MCPPrompt,
    PromptArgument as MCPPromptArgument,
    Resource as MCPResource,
    Tool as MCPTool,
)

from mcp.server.state.builder import StateMachineDefinition
from mcp.server.state.machine import SessionScopedStateMachine
from mcp.server.state.prompts.state_aware_prompt_manager import StateAwarePromptManager
from mcp.server.state.resources.state_aware_resource_manager import StateAwareResourceManager
from mcp.server.state.store import ServerSessionData
from mcp.server.state.tools.state_aware_tool_manager import StateAwareToolManager


logger = get_logger(f"{__name__}.StatefulMCP")

class StatefulMCP(FastMCP[LifespanResultT]):
    """FastMCP with a session-scoped StateMachine and state-aware managers.

    Overrides FastMCP handlers:
      - list_tools / call_tool
      - list_resources / read_resource
      - list_prompts / get_prompt

    Session scoping:
      Uses the low-level “session initialized” hook to bind per-session state.
      If the hook is unavailable, the machine behaves globally.

    Session data storage:
      Each session gets its own data store at initialization. 
      In handlers it is available as `ctx.session_store`.

    Important:
      Define states via `statebuilder`; otherwise no tools/resources/prompts are
      visible and startup validation may fail (e.g., missing initial state).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Parent initialization sets up _mcp_server and native managers
        super().__init__(*args, **kwargs)

        # Public DSL to define/validate the state machine
        self._state_definition = StateMachineDefinition(self._tool_manager, self._resource_manager, self._prompt_manager)

        # Session-scoped state machine runtime (built in run())
        self._state_machine: SessionScopedStateMachine | None = None
        self._registered_sessions: set[str] = set()
        self._reg_lock = anyio.Lock()

        # Per-session user data stores
        self._session_stores: dict[str, ServerSessionData] = {}
        self._stores_lock = anyio.Lock()

        # TODO: !!! Add a cleanup for session on disconnect or a certain amount of time !!!

        # Our state-aware managers (created in run())
        self._stateful_tools: StateAwareToolManager | None = None
        self._stateful_resources: StateAwareResourceManager | None = None
        self._stateful_prompts: StateAwarePromptManager | None = None

        # Optional low-level hook: register a session exactly once at MCP Initialized.
        # State machine & managers are guaranteed to exist by the time requests can arrive (after run()).
        if hasattr(self._mcp_server, "set_session_initialized_hook"):
            self._mcp_server.set_session_initialized_hook(self._on_session_initialized)

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
    
    @property
    def session_store(self) -> ServerSessionData:
        """Return the data store for the current session. 
        Raises an error if called outside of a request context.
        """
        sid = self._sid()  # raises error if called outside of request 
        store = self._session_stores.get(sid)
        if store is None:
            msg = (
                f"No session store registered for session '{sid}'."
                "This indicates the session initialization hook did not run."
            )
            raise ValueError(msg)
        return store

    def run(
        self,
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        mount_path: str | None = None,
    ) -> None:
        """Run the server. Build state machine and initialize state-aware managers once."""
        self._build_state_machine_once()
        self._init_stateful_managers_once()
        return super().run(transport=transport, mount_path=mount_path)

    ### State machine lifecycle & manager wiring 

    def _build_state_machine_once(self) -> None:
        """Startup-only state machine bootstrap.

        Create a session-scoped machine using a resolver that reads the current
        session id from the request context (falls back to global when none).

        Build & validate the machine once after all user registrations.
        """
        if self._state_machine is not None:
            return

        logger.info("State machine bootstrap: begin building and validating from DSL")

        internal = self._state_definition._to_internal_builder()  # pyright: ignore[reportPrivateUsage]

        def _resolve_sid() -> str | None:
            try:
                sid = self._sid()
                logger.debug("State machine resolver: resolved session id %s", sid)
                return sid
            except Exception as e:
                logger.warning("State machine resolver: could not resolve session id (%s); falling back to global mode", e)
                return None

        self._state_machine = internal.build_session_scoped(session_resolver=_resolve_sid)
        logger.info("State machine bootstrap: build complete and ready")

    def _init_stateful_managers_once(self) -> None:
        """Instantiate state-aware managers once the state machine exists."""
        if self._state_machine is None:
            raise RuntimeError("State machine must be built before initializing stateful managers")
        
        if self._stateful_tools is None:
            logger.info("State machine wiring: initializing StateAwareToolManager")
            self._stateful_tools = StateAwareToolManager(
                state_machine=self._state_machine,
                tool_manager=self._tool_manager,
            )

        if self._stateful_resources is None:
            logger.info("State machine wiring: initializing StateAwareResourceManager")
            self._stateful_resources = StateAwareResourceManager(
                state_machine=self._state_machine,
                resource_manager=self._resource_manager,
            )

        if self._stateful_prompts is None:
            logger.info("State machine wiring: initializing StateAwarePromptManager")
            self._stateful_prompts = StateAwarePromptManager(
                state_machine=self._state_machine,
                prompt_manager=self._prompt_manager,
            )

    async def _on_session_initialized(self, session_id: str) -> None:
        """One-time registration for a newly initialized session.

        Ensures a state machine session entry and creates the per-session data store.
        Assumes state machine and managers were created in `run()`.
        """
        logger.info("Session init: received session id %s; starting initialization", session_id)

        if self._state_machine is None:
            raise RuntimeError("State machine not initialized; `run()` must be called before serving requests")

        # ensure state machine session
        if session_id not in self._registered_sessions:
            async with self._reg_lock:
                if session_id not in self._registered_sessions:
                    self._state_machine.ensure_session(session_id)
                    self._registered_sessions.add(session_id)
                    logger.info("Session init: registered state machine session for %s", session_id)
        else:
            logger.debug("Session init: state machine session already registered for %s", session_id)

        # ensure data store
        if session_id not in self._session_stores:
            async with self._stores_lock:
                if session_id not in self._session_stores:
                    self._session_stores.setdefault(session_id, ServerSessionData())
                    logger.info("Session init: created data store for %s", session_id)
        else:
            logger.debug("Session init: data store already exists for %s", session_id)

    ### Helpers
    
    def get_context(self) -> FastMCPContext[ServerSession, LifespanResultT, Request]:
        """Override FastMCP.

        Return the request Context and attach a `session_store` alias so handlers and tools
        can access per-session data without modifying FastMCP internals. 
        """
        base = super().get_context()
        return StatefulMCPContext(
            request_context=base.request_context,
            statefulmcp=self,                  # pass the server instance
            session_store=self.session_store,  # resolved per-session
        )

    def _sid(self) -> str:
        """Current session_id as a string."""
        return self._mcp_server.request_context.session.session_id # from lowlevel, to avoid recurison (session_store)

    ### Overridden FastMCP methods (delegating to state-aware managers)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        """Override FastMCP.

        Execute via the state-aware ToolManager. Access is constrained by the
        session-scoped state machine to tools allowed in the *current state* of the *current session*. 
        
        Forwards the execution context so that tools can access session data.

        Example usage::

            def tool_with_context(ctx: Context) -> str:
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


### Extend the FastMCP Context with session store

class StatefulMCPContext(
    FastMCPContext[ServerSessionT, LifespanContextT, RequestT],
    Generic[ServerSessionT, LifespanContextT, RequestT],
):
    """FastMCP Context extended with a per-session ServerSessionData."""

    # Context is a Pydantic BaseModel. Adding attributes dynamically (setattr) is typically blocked.
    # PrivateAttr keeps the store out of validation/serialization/schema.
    _session_store: ServerSessionData = PrivateAttr()

    def __init__(
        self,
        request_context: RequestContext[ServerSessionT, LifespanContextT, RequestT] | None,
        statefulmcp: StatefulMCP,  
        session_store: ServerSessionData,
        **kwargs: Any,
    ):
        super().__init__(request_context=request_context, fastmcp=statefulmcp, **kwargs)
        self._session_store = session_store

    @property
    def session_store(self) -> ServerSessionData:
        return self._session_store