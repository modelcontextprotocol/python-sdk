from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic
from urllib.parse import urlparse
from urllib.request import url2pathname

from pydantic import AnyUrl, BaseModel

from mcp.server.context import LifespanContextT, RequestT, ServerRequestContext
from mcp.server.elicitation import (
    ElicitationResult,
    ElicitSchemaModelT,
    UrlElicitationResult,
    elicit_url,
    elicit_with_validation,
)
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import LoggingLevel

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

    # TODO(maxisbey): Consider making request_context/mcp_server required, or refactor Context entirely.
    def __init__(
        self,
        *,
        request_context: ServerRequestContext[LifespanContextT, RequestT] | None = None,
        mcp_server: MCPServer | None = None,
        # TODO(Marcelo): We should drop this kwargs parameter.
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._request_context = request_context
        self._mcp_server = mcp_server

    @property
    def mcp_server(self) -> MCPServer:
        """Access to the MCPServer instance."""
        if self._mcp_server is None:  # pragma: no cover
            raise ValueError("Context is not available outside of a request")
        return self._mcp_server  # pragma: no cover

    @property
    def request_context(self) -> ServerRequestContext[LifespanContextT, RequestT]:
        """Access to the underlying request context."""
        if self._request_context is None:  # pragma: no cover
            raise ValueError("Context is not available outside of a request")
        return self._request_context

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        """Report progress for the current operation.

        Args:
            progress: Current progress value (e.g., 24)
            total: Optional total value (e.g., 100)
            message: Optional message (e.g., "Starting render...")
        """
        progress_token = self.request_context.meta.get("progress_token") if self.request_context.meta else None

        if progress_token is None:  # pragma: no cover
            return

        await self.request_context.session.send_progress_notification(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            related_request_id=self.request_id,
        )

    async def read_resource(self, uri: str | AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource by URI.

        Args:
            uri: Resource URI to read

        Returns:
            The resource content as either text or bytes
        """
        assert self._mcp_server is not None, "Context is not available outside of a request"
        return await self._mcp_server.read_resource(uri, self)

    async def assert_within_roots(self, path: str | Path) -> None:
        """Assert that a filesystem path is within the client's declared roots.

        Provides server-side enforcement of the filesystem boundaries declared by
        the client via the Roots capability. Call this at the start of any tool
        that accepts a user-provided path, to prevent the tool from accessing
        files outside the client's declared scope.

        Args:
            path: The filesystem path to validate. Accepts a string or Path.
                Relative paths and symlinks are resolved before comparison.

        Raises:
            PermissionError: If the path is outside every declared root, or if
                the client has declared no roots.

        Example:
            ```python
            @server.tool()
            async def read_file(path: str, ctx: Context) -> str:
                await ctx.assert_within_roots(path)
                with open(path) as f:
                    return f.read()
            ```
        """
        target = Path(path).resolve()

        result = await self.request_context.session.list_roots()

        for root in result.roots:
            root_path = Path(url2pathname(urlparse(str(root.uri)).path)).resolve()
            if target.is_relative_to(root_path):
                return

        raise PermissionError(f"Path {target} is not within any declared root")

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
        await self.request_context.session.send_log_message(
            level=level,
            data=data,
            logger=logger_name,
            related_request_id=self.request_id,
        )

    @property
    def client_id(self) -> str | None:
        """Get the client ID if available."""
        return self.request_context.meta.get("client_id") if self.request_context.meta else None  # pragma: no cover

    @property
    def request_id(self) -> str:
        """Get the unique ID for this request."""
        return str(self.request_context.request_id)

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
        if self._request_context and self._request_context.close_sse_stream:  # pragma: no cover
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
    async def debug(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send a debug log message."""
        await self.log("debug", data, logger_name=logger_name)

    async def info(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send an info log message."""
        await self.log("info", data, logger_name=logger_name)

    async def warning(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send a warning log message."""
        await self.log("warning", data, logger_name=logger_name)

    async def error(self, data: Any, *, logger_name: str | None = None) -> None:
        """Send an error log message."""
        await self.log("error", data, logger_name=logger_name)
