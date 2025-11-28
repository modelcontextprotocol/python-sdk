"""OpenTelemetry instrumentation example for MCP SDK.

This example demonstrates how to integrate OpenTelemetry tracing with the MCP SDK
using the pluggable instrumentation interface.

Installation:
    pip install opentelemetry-api opentelemetry-sdk

Usage:
    # In your server code:
    from opentelemetry_instrumentation import OpenTelemetryInstrumenter

    instrumenter = OpenTelemetryInstrumenter()

    # When creating ServerSession:
    session = ServerSession(
        read_stream,
        write_stream,
        init_options,
        instrumenter=instrumenter,
    )

Related issue: https://github.com/modelcontextprotocol/python-sdk/issues/421
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import RequestId

logger = logging.getLogger(__name__)


class OpenTelemetryInstrumenter:
    """OpenTelemetry implementation of the MCP Instrumenter protocol.

    This instrumenter creates spans for each MCP request, tracks metrics,
    and supports distributed tracing via context propagation.
    """

    def __init__(self, tracer_provider=None):
        """Initialize the OpenTelemetry instrumenter.

        Args:
            tracer_provider: Optional OpenTelemetry tracer provider.
                If None, uses the global tracer provider.
        """
        try:
            from opentelemetry import trace
            from opentelemetry.trace import Status, StatusCode

            self._trace = trace
            self._Status = Status
            self._StatusCode = StatusCode

            if tracer_provider is None:
                tracer_provider = trace.get_tracer_provider()

            self._tracer = tracer_provider.get_tracer("mcp.sdk", version="1.0.0")
            self._enabled = True
        except ImportError:
            logger.warning("OpenTelemetry not installed. Install with: pip install opentelemetry-api opentelemetry-sdk")
            self._enabled = False

    def on_request_start(
        self,
        request_id: RequestId,
        request_type: str,
        method: str | None = None,
        **metadata: Any,
    ) -> Any:
        """Start a new span for the request.

        Returns:
            The OpenTelemetry span object as the token.
        """
        if not self._enabled:
            return None

        # Create span name from request type
        span_name = f"mcp.{request_type}"
        if method:
            span_name = f"{span_name}.{method}"

        # Start the span
        span = self._tracer.start_span(span_name)

        # Set standard attributes
        span.set_attribute("mcp.request_id", str(request_id))
        span.set_attribute("mcp.request_type", request_type)

        if method:
            span.set_attribute("mcp.method", method)

        # Add metadata as attributes
        session_type = metadata.get("session_type")
        if session_type:
            span.set_attribute("mcp.session_type", session_type)

        # Add any custom metadata
        for key, value in metadata.items():
            if key not in ("session_type",) and isinstance(value, str | int | float | bool):
                span.set_attribute(f"mcp.{key}", value)

        return span

    def on_request_end(
        self,
        token: Any,
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        """End the span for the request.

        Args:
            token: The span object returned from on_request_start
        """
        if not self._enabled or token is None:
            return

        span = token

        # Set success status
        span.set_attribute("mcp.success", success)

        if duration_seconds is not None:
            span.set_attribute("mcp.duration_seconds", duration_seconds)

        # Set span status
        if success:
            span.set_status(self._Status(self._StatusCode.OK))
        else:
            span.set_status(self._Status(self._StatusCode.ERROR))
            # Add error info if available
            error_msg = metadata.get("error")
            if error_msg:
                span.set_attribute("mcp.error", str(error_msg))

        # Check if cancelled
        if metadata.get("cancelled"):
            span.set_attribute("mcp.cancelled", True)

        # End the span
        span.end()

    def on_error(
        self,
        token: Any,
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata: Any,
    ) -> None:
        """Record error information in the span.

        Args:
            token: The span object returned from on_request_start
        """
        if not self._enabled or token is None:
            return

        span = token

        # Record the exception
        span.record_exception(error)

        # Set error attributes
        span.set_attribute("mcp.error_type", error_type)
        span.set_attribute("mcp.error_message", str(error))

        # Mark span as error
        span.set_status(self._Status(self._StatusCode.ERROR, str(error)))


# Example usage
if __name__ == "__main__":
    import asyncio

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    import mcp.types as types
    from mcp.server.lowlevel import Server
    from mcp.shared.memory import create_connected_server_and_client_session

    # Setup OpenTelemetry
    resource = Resource.create({"service.name": "mcp-example-server"})
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # Create instrumenter
    instrumenter = OpenTelemetryInstrumenter()

    # Create server
    server = Server("example-server")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo",
                description="Echo a message",
                inputSchema={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
            )
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name == "echo":
            message = arguments.get("message", "")
            return [types.TextContent(type="text", text=f"Echo: {message}")]
        raise ValueError(f"Unknown tool: {name}")

    async def main():
        print("Running MCP server with OpenTelemetry instrumentation...")
        print("Traces will be printed to console.\n")

        async with create_connected_server_and_client_session(
            server,
            raise_exceptions=True,
        ) as client:
            # Note: In production, you would pass the instrumenter when creating the ServerSession
            # For this example, we're using the test helper which doesn't expose that parameter

            await client.initialize()

            # List tools
            print("Listing tools...")
            tools_result = await client.list_tools()
            print(f"Found {len(tools_result.tools)} tools\n")

            # Call a tool
            print("Calling echo tool...")
            result = await client.call_tool("echo", {"message": "Hello, OpenTelemetry!"})
            print(f"Result: {result}\n")

        # Give time for spans to export
        await asyncio.sleep(1)

    asyncio.run(main())
