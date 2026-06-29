from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, Generic, cast

from mcp_types import ClientCapabilities, InputResponseRequestParams, InputResponses, LoggingLevel
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
from mcp.shared.exceptions import MCPDeprecationWarning

if TYPE_CHECKING:
    from mcp.server.mcpserver.server import MCPServer


class Context(BaseModel, Generic[LifespanContextT, RequestT]):
    """Request-scoped access to MCP capabilities.

    Injected into tool and resource functions that request it via a `Context`-annotated
    parameter (any name; optional - functions that don't need it can omit it):

    ```python
    @server.tool()
    async def my_tool(x: int, ctx: Context) -> str:
        await ctx.report_progress(50, 100)
        data = await ctx.read_resource("resource://data")
        return str(x)
    ```
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
        if self._mcp_server is None:  # pragma: no cover
            raise ValueError("Context is not available outside of a request")
        return self._mcp_server  # pragma: no cover

    @property
    def request_context(self) -> ServerRequestContext[LifespanContextT, RequestT]:
        """Access to the underlying request context."""
        if self._request_context is None:
            raise ValueError("Context is not available outside of a request")
        return self._request_context

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the current operation."""
        await self.request_context.session.report_progress(progress, total, message)

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource by URI.

        Raises:
            ResourceNotFoundError: If no resource or template matches the URI.
            ResourceError: If template creation or resource reading fails.
        """
        assert self._mcp_server is not None, "Context is not available outside of a request"
        return await self._mcp_server.read_resource(uri, self)

    async def elicit(
        self,
        message: str,
        schema: type[ElicitSchemaModelT],
    ) -> ElicitationResult[ElicitSchemaModelT]:
        """Elicit information from the client/user during a tool's execution.

        Per the specification, `schema` may only contain primitive-typed fields. Check
        `result.action` for accept/decline/cancel; `result.data` is populated only when
        the action is "accept" and validation succeeded.
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

        Directs the user to an external URL for out-of-band interactions whose data
        must not pass through the MCP client or LLM context (credentials, OAuth flows,
        payments). The result only indicates whether the user consented to navigate;
        when the interaction completes, call
        `ctx.session.send_elicit_complete(elicitation_id)` to notify the client.
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
        """Send a log message to the client. `data` may be any JSON-serializable value."""
        await self.request_context.session.send_log_message(  # pyright: ignore[reportDeprecated]
            level=level,
            data=data,
            logger=logger_name,
            related_request_id=self.request_id,
        )

    # TODO(maxisbey): see if this is needed otherwise remove
    @property
    def client_id(self) -> str | None:
        """The client ID from the MCP request's `_meta` params, if available.

        Not the OAuth bearer token's client ID - for that, use `get_access_token().client_id`.
        """
        return self.request_context.meta.get("client_id") if self.request_context.meta else None  # pragma: no cover

    @property
    def headers(self) -> Mapping[str, str] | None:
        """Request headers carried by this message, when the transport has them.

        Populated by HTTP-based transports; `None` on stdio. Headers are client-supplied
        input - never treat one as an identity assertion.
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

        `None` on the initial round, or when the client retried without responses.
        """
        return self._input_params.input_responses if self._input_params else None

    @property
    def request_state(self) -> str | None:
        """Opaque state echoed from a prior `InputRequiredResult.request_state`; `None` on the initial round."""
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
        """Close the current request's SSE stream to trigger client reconnection.

        Events keep accruing in the event store and are replayed when the client
        reconnects with Last-Event-ID, enabling polling behavior during long-running
        operations. No-op unless using StreamableHTTP transport with an event_store.
        """
        if self._request_context and self._request_context.close_sse_stream:  # pragma: no branch
            await self._request_context.close_sse_stream()

    async def close_standalone_sse_stream(self) -> None:
        """Close the standalone GET SSE stream used for unsolicited server-to-client notifications.

        The client SHOULD reconnect with Last-Event-ID to resume. No-op unless using
        StreamableHTTP transport with an event_store. Known gap: client reconnection
        for standalone GET streams is not implemented.
        """
        if self._request_context and self._request_context.close_standalone_sse_stream:  # pragma: no cover
            await self._request_context.close_standalone_sse_stream()

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
