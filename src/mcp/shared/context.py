from dataclasses import dataclass
from typing import Any, Generic

from typing_extensions import TypeVar

from mcp.shared.session import BaseSession
from mcp.types import RequestId, RequestParams

SessionT = TypeVar("SessionT", bound=BaseSession[Any, Any, Any, Any, Any])
LifespanContextT = TypeVar("LifespanContextT")
RequestT = TypeVar("RequestT", default=Any)


@dataclass
class RequestContext(Generic[SessionT, LifespanContextT, RequestT]):
    """Context object containing information about the current MCP request.

    This is the fundamental context object in the MCP Python SDK that provides access
    to request-scoped information and capabilities. It's created automatically for each
    incoming client request and contains everything needed to process that request,
    including the session for client communication, request metadata, and any resources
    initialized during server startup.

    The RequestContext is available throughout the request lifecycle and provides the
    foundation for both low-level and high-level SDK usage patterns. In the low-level
    SDK, you access it via [`Server.request_context`][mcp.server.lowlevel.server.Server.request_context].
    In FastMCP, it's wrapped by the more convenient [`Context`][mcp.server.fastmcp.Context] 
    class that provides the same functionality with additional helper methods.

    ## Request lifecycle

    The RequestContext is created when a client request arrives and destroyed when the
    request completes. It's only available during request processing - attempting to
    access it outside of a request handler will raise a `LookupError`.

    ## Access patterns

    **Low-level SDK**: Access directly via the server's request_context property:

    ```python
    @app.call_tool()
    async def my_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:
        ctx = app.request_context  # Get the RequestContext
        await ctx.session.send_log_message(level="info", data="Processing...")
    ```

    **FastMCP**: Use the injected Context wrapper instead:

    ```python
    @mcp.tool()
    async def my_tool(data: str, ctx: Context) -> str:
        await ctx.info("Processing...")  # Context provides convenience methods
    ```

    ## Lifespan context integration

    Resources initialized during server startup (databases, connections, etc.) are
    accessible through the `lifespan_context` attribute, enabling request handlers
    to use shared resources safely:

    ```python
    # Server startup - initialize shared resources
    @asynccontextmanager
    async def server_lifespan(server):
        db = await Database.connect()
        try:
            yield {"db": db}
        finally:
            await db.disconnect()

    # Request handling - access shared resources
    @server.call_tool()  
    async def query_data(name: str, arguments: dict[str, Any]):
        ctx = server.request_context
        db = ctx.lifespan_context["db"]  # Access startup resource
        results = await db.query(arguments["query"])
    ```

    Attributes:
        request_id: Unique identifier for the current request as a `RequestId`.
            Use this for logging, tracing, or linking related operations.
        meta: Optional request metadata including progress tokens and other client-provided
            information. May be `None` if no metadata was provided.
        session: The [`ServerSession`][mcp.server.session.ServerSession] for communicating
            with the client. Use this to send responses, log messages, or check capabilities.
        lifespan_context: Application-specific resources initialized during server startup.
            Contains any objects yielded by the server's lifespan function.
        request: The original request object from the client, if available. May be `None`
            for some request types.

    Note:
        This object is request-scoped and thread-safe within that scope. Each request
        gets its own RequestContext instance. Don't store references to it beyond the
        request lifecycle, as it becomes invalid when the request completes.
    """

    request_id: RequestId
    meta: RequestParams.Meta | None
    session: SessionT
    lifespan_context: LifespanContextT
    request: RequestT | None = None
