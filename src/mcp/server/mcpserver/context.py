from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Generic, cast

from mcp_types import ClientCapabilities, InputRequiredResult, InputResponseRequestParams, InputResponses, LoggingLevel
from pydantic import AnyUrl, BaseModel
from typing_extensions import deprecated

from mcp.server.context import LifespanContextT, RequestT, ServerRequestContext
from mcp.server.elicitation import (
    ElicitationResult,
    ElicitSchemaModelT,
    UrlElicitationResult,
    elicit_url,
    elicit_with_validation,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.subscriptions import PromptsListChanged, ResourcesListChanged, ResourceUpdated, ToolsListChanged
from mcp.shared.exceptions import MCPDeprecationWarning

if TYPE_CHECKING:
    from mcp.server.mcpserver.server import MCPServer


class Context(BaseModel, Generic[LifespanContextT, RequestT]):
    """Context object providing access to MCP capabilities.

    This provides a cleaner interface to MCP's RequestContext functionality.
    It gets injected into tool and resource functions that request it via type hints.

    To use context in a tool function, add a parameter with the Context type annotation:

    ```python
    @server.tool()
    async def my_tool(x: int, ctx: Context) -> str:
        # Log messages to the client
        await ctx.info(f"Processing {x}")
        await ctx.debug("Debug info")
        await ctx.warning("Warning message")
        await ctx.error("Error message")

        # Report progress
        await ctx.report_progress(50, 100)

        # Access resources
        data = await ctx.read_resource("resource://data")

        # Get request info
        request_id = ctx.request_id
        client_id = ctx.client_id

        return str(x)
    ```

    The context parameter name can be anything as long as it's annotated with Context.
    The context is optional - tools that don't need it can omit the parameter.
    """

    _request_context: ServerRequestContext[LifespanContextT, RequestT] | None
    _mcp_server: MCPServer | None
    _input_params: InputResponseRequestParams | None

    # TODO(maxisbey): Consider making request_context/mcp_server required, or refactor Context entirely.
    def __init__(
        self,
        *,
        request_context: ServerRequestContext[LifespanContextT, RequestT] | None = None,
        mcp_server: MCPServer | None = None,
        input_params: InputResponseRequestParams | None = None,
        # TODO(Marcelo): We should drop this kwargs parameter.
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._request_context = request_context
        self._mcp_server = mcp_server
        self._input_params = input_params

    @property
    def mcp_server(self) -> MCPServer:
        """Access to the MCPServer instance."""
        if self._mcp_server is None:
            raise ValueError("Context is not available outside of a request")
        return self._mcp_server

    @property
    def request_context(self) -> ServerRequestContext[LifespanContextT, RequestT]:
        """Access to the underlying request context."""
        if self._request_context is None:
            raise ValueError("Context is not available outside of a request")
        return self._request_context

    def _nested_invocation(self) -> Context[LifespanContextT, RequestT]:
        """A Context for invoking another handler's function from inside this request.

        Shares the request infrastructure (session, request metadata, lifespan) but
        carries no `input_responses`/`request_state`: those are addressed to the wire
        request's own target — their keys are ones that handler minted — so a nested
        invocation always starts on round one.
        """
        return Context(request_context=self._request_context, mcp_server=self._mcp_server)

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value (e.g., 24)
            total: Optional total value (e.g., 100)
            message: Optional message (e.g., "Starting render...")
        """
        await self.request_context.session.report_progress(progress, total, message)

    def notify_tools_changed(self) -> None:
        """Publish a tools list-changed event to `subscriptions/listen` subscribers."""
        self.mcp_server.subscriptions.publish(ToolsListChanged())

    def notify_prompts_changed(self) -> None:
        """Publish a prompts list-changed event to `subscriptions/listen` subscribers."""
        self.mcp_server.subscriptions.publish(PromptsListChanged())

    def notify_resources_changed(self) -> None:
        """Publish a resources list-changed event to `subscriptions/listen` subscribers."""
        self.mcp_server.subscriptions.publish(ResourcesListChanged())

    def notify_resource_updated(self, uri: str | AnyUrl) -> None:
        """Publish a resource-updated event for `uri` to `subscriptions/listen` subscribers."""
        self.mcp_server.subscriptions.publish(ResourceUpdated(uri=str(uri)))

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource by URI.

        This is a content reader: an `InputRequiredResult` returned by a
        resource template function (the 2026-07-28 multi-round-trip flow)
        raises here, and the nested template never sees this request's
        `input_responses`/`request_state` — those answer the outer handler's
        own questions, so the template always behaves as round one. A handler
        that wants to receive and forward an `InputRequiredResult` as its own
        result calls `MCPServer.read_resource(uri, context)` instead — but
        not from a tool whose dependencies elicit via `Resolve(...)`: the
        resolver owns that tool's `request_state` channel, and a forwarded
        result's state would clobber it.

        Args:
            uri: Resource URI to read

        Returns:
            The resource content as either text or bytes

        Raises:
            ResourceNotFoundError: If no resource or template matches the URI.
            ResourceError: If template creation or resource reading fails.
            RuntimeError: If the resource returned an `InputRequiredResult`.
        """
        assert self._mcp_server is not None, "Context is not available outside of a request"
        result = await self._mcp_server.read_resource(uri, self._nested_invocation())
        if isinstance(result, InputRequiredResult):
            raise RuntimeError(
                "Resource returned InputRequiredResult; ctx.read_resource() only returns "
                "content — use MCPServer.read_resource(uri, context) to receive and forward it."
            )
        return result

    async def elicit(
        self,
        message: str,
        schema: type[ElicitSchemaModelT],
    ) -> ElicitationResult[ElicitSchemaModelT]:
        """Elicit information from the client/user.

        This method can be used to interactively ask for additional information from the
        client within a tool's execution. The client might display the message to the
        user and collect a response according to the provided schema. If the client
        is an agent, it might decide how to handle the elicitation -- either by asking
        the user or automatically generating a response.

        Args:
            message: Message to present to the user
            schema: A Pydantic model class defining the expected response structure.
                    According to the specification, only primitive types are allowed.

        Returns:
            An ElicitationResult containing the action taken and the data if accepted

        Note:
            Check the result.action to determine if the user accepted, declined, or cancelled.
            The result.data will only be populated if action is "accept" and validation succeeded.
        """

        return await elicit_with_validation(
            session=self.request_context.session,
            message=message,
            schema=schema,
            related_request_id=self.request_id,
        )

    async def elicit_url(
        self,
        message: str,
        url: str,
        elicitation_id: str,
    ) -> UrlElicitationResult:
        """Request URL mode elicitation from the client.

        This directs the user to an external URL for out-of-band interactions
        that must not pass through the MCP client. Use this for:
        - Collecting sensitive credentials (API keys, passwords)
        - OAuth authorization flows with third-party services
        - Payment and subscription flows
        - Any interaction where data should not pass through the LLM context

        The response indicates whether the user consented to navigate to the URL.
        The actual interaction happens out-of-band. When the elicitation completes,
        call `ctx.session.send_elicit_complete(elicitation_id)` to notify the client.

        Args:
            message: Human-readable explanation of why the interaction is needed
            url: The URL the user should navigate to
            elicitation_id: Unique identifier for tracking this elicitation

        Returns:
            UrlElicitationResult indicating accept, decline, or cancel
        """
        return await elicit_url(
            session=self.request_context.session,
            message=message,
            url=url,
            elicitation_id=elicitation_id,
            related_request_id=self.request_id,
        )

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def log(
        self,
        level: LoggingLevel,
        data: Any,
        *,
        logger_name: str | None = None,
    ) -> None:
        """Send a log message to the client.

        Args:
            level: Log level (debug, info, notice, warning, error, critical,
                alert, emergency)
            data: The data to be logged. Any JSON serializable type is allowed
                (string, dict, list, number, bool, etc.) per the MCP specification.
            logger_name: Optional logger name
        """
        await self.request_context.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level=level,
            data=data,
            logger=logger_name,
            related_request_id=self.request_id,
        )

    # TODO(maxisbey): see if this is needed otherwise remove
    @property
    def client_id(self) -> str | None:
        """Get the client ID if available.

        Note: this reads from the MCP request's `_meta` params, not the OAuth
        bearer token. For that, use `get_access_token().client_id`.
        """
        return self.request_context.meta.get("client_id") if self.request_context.meta else None  # pragma: no cover

    @property
    def headers(self) -> Mapping[str, str] | None:
        """Request headers carried by this message, when the transport has them.

        Populated by HTTP-based transports; `None` on stdio or when the
        transport's request object carries no headers. Headers are
        client-supplied input - never treat one as an identity assertion.
        """
        return cast("Mapping[str, str] | None", getattr(self.request_context.request, "headers", None))

    @property
    def request_id(self) -> str:
        """Get the unique ID for this request."""
        return str(self.request_context.request_id)

    @property
    def protocol_version(self) -> str | None:
        """The negotiated protocol version, or `None` outside of an active request."""
        return self._request_context.protocol_version if self._request_context is not None else None

    @property
    def input_responses(self) -> InputResponses | None:
        """Client responses to a prior `InputRequiredResult.input_requests`.

        `None` on the initial round, or when the client retried without
        responses.
        """
        return self._input_params.input_responses if self._input_params else None

    @property
    def request_state(self) -> str | None:
        """Opaque state echoed from a prior `InputRequiredResult.request_state`.

        `None` on the initial round.
        """
        return self._input_params.request_state if self._input_params else None

    @property
    def client_capabilities(self) -> ClientCapabilities | None:
        """The client's declared capabilities for this connection.

        `None` when the client supplied no client info (e.g. an anonymous
        stateless request without the reserved `_meta` keys).
        """
        client_params = self.request_context.session.client_params
        return client_params.capabilities if client_params else None

    @property
    def session(self):
        """Access to the underlying session for advanced usage."""
        return self.request_context.session

    async def close_sse_stream(self) -> None:
        """Close the SSE stream to trigger client reconnection.

        This method closes the HTTP connection for the current request, triggering
        client reconnection. Events continue to be stored in the event store and will
        be replayed when the client reconnects with Last-Event-ID.

        Use this to implement polling behavior during long-running operations -
        the client will reconnect after the retry interval specified in the priming event.

        Note:
            This is a no-op if not using StreamableHTTP transport with event_store.
            The callback is only available when event_store is configured.
        """
        if self._request_context and self._request_context.close_sse_stream:  # pragma: no branch
            await self._request_context.close_sse_stream()

    async def close_standalone_sse_stream(self) -> None:
        """Close the standalone GET SSE stream to trigger client reconnection.

        This method closes the HTTP connection for the standalone GET stream used
        for unsolicited server-to-client notifications. The client SHOULD reconnect
        with Last-Event-ID to resume receiving notifications.

        Note:
            This is a no-op if not using StreamableHTTP transport with event_store.
            Currently, client reconnection for standalone GET streams is NOT
            implemented - this is a known gap.
        """
        if self._request_context and self._request_context.close_standalone_sse_stream:  # pragma: no cover
            await self._request_context.close_standalone_sse_stream()

    # Convenience methods for common log levels
    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def debug(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send a debug log message."""
        await self.log("debug", data, logger_name=logger_name)  # pyright: ignore[reportDeprecated]

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def info(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send an info log message."""
        await self.log("info", data, logger_name=logger_name)  # pyright: ignore[reportDeprecated]

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def warning(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send a warning log message."""
        await self.log("warning", data, logger_name=logger_name)  # pyright: ignore[reportDeprecated]

    @deprecated("The logging capability is deprecated as of 2026-07-28 (SEP-2577).", category=MCPDeprecationWarning)
    async def error(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send an error log message."""
        await self.log("error", data, logger_name=logger_name)  # pyright: ignore[reportDeprecated]
