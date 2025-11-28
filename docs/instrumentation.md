# Instrumentation

The MCP Python SDK provides a pluggable instrumentation interface for monitoring request/response lifecycle. This enables integration with OpenTelemetry, custom metrics, logging frameworks, and other observability tools.

**Related issue**: [#421 - Adding OpenTelemetry to MCP SDK](https://github.com/modelcontextprotocol/python-sdk/issues/421)

## Overview

The `Instrumenter` protocol defines three hooks:

- `on_request_start`: Called when a request starts processing, **returns a token**
- `on_request_end`: Called when a request completes, **receives the token**
- `on_error`: Called when an error occurs, **receives the token**

The token-based design allows instrumenters to maintain state (like OpenTelemetry spans) between `on_request_start` and `on_request_end` without needing external storage or side-channels.

All methods are optional (no-op implementations are valid). Exceptions raised by instrumentation hooks are logged but do not affect request processing.

## Basic Usage

### Server-Side Instrumentation

```python
from typing import Any
from mcp.server.lowlevel import Server
from mcp.shared.instrumentation import Instrumenter
from mcp.types import RequestId

class MyInstrumenter:
    """Custom instrumenter implementation."""
    
    def on_request_start(
        self,
        request_id: RequestId,
        request_type: str,
        method: str | None = None,
        **metadata,
    ) -> Any:
        """Return a token (any value) to track this request."""
        print(f"Request {request_id} started: {request_type}")
        # Return a token - can be anything (dict, object, etc.)
        return {"request_id": request_id, "start_time": time.time()}
    
    def on_request_end(
        self,
        token: Any,  # Receives the token from on_request_start
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata,
    ) -> None:
        """Process the completed request using the token."""
        status = "succeeded" if success else "failed"
        print(f"Request {request_id} {status} in {duration_seconds:.3f}s")
        print(f"Token data: {token}")
    
    def on_error(
        self,
        token: Any,  # Receives the token from on_request_start
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata,
    ) -> None:
        """Handle errors using the token."""
        print(f"Error in request {request_id}: {error_type} - {error}")

# Create server with custom instrumenter
server = Server("my-server")

# Pass instrumenter when running the server
async def run_server():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
            instrumenter=MyInstrumenter(),
        )
```

### Client-Side Instrumentation

```python
from mcp.client.session import ClientSession
from mcp.shared.instrumentation import Instrumenter

# Create client session with instrumenter
async with ClientSession(
    read_stream=read_stream,
    write_stream=write_stream,
    instrumenter=MyInstrumenter(),
) as session:
    await session.initialize()
    # Use session...
```

### Why Tokens?

The token-based design solves a key problem: **how do you maintain state between `on_request_start` and `on_request_end`?**

Without tokens, instrumenters would need to use external storage (like a dictionary keyed by `request_id`) to track state:

```python
# ❌ Old approach - requires external storage
class OldInstrumenter:
    def __init__(self):
        self.spans = {}  # Need to manage this dict
    
    def on_request_start(self, request_id, ...):
        span = create_span(...)
        self.spans[request_id] = span  # Store externally
    
    def on_request_end(self, request_id, ...):
        span = self.spans.pop(request_id)  # Retrieve from storage
        span.end()
```

With tokens, state passes directly through the SDK:

```python
# ✅ New approach - token is returned and passed back
class NewInstrumenter:
    def on_request_start(self, request_id, ...):
        span = create_span(...)
        return span  # Return directly
    
    def on_request_end(self, token, request_id, ...):
        span = token  # Receive directly
        span.end()
```

This is especially important for OpenTelemetry, where spans need to be kept alive.

## Metadata

Instrumentation hooks receive metadata via `**metadata` keyword arguments:

- `on_request_start` metadata:
  - `session_type`: "server" or "client"
  - Any additional context provided by the framework

- `on_request_end` metadata:
  - `cancelled`: True if the request was cancelled
  - `error`: Error message if request failed
  - Any additional context

- `on_error` metadata:
  - Additional error context

## Request ID

The `request_id` parameter is consistent across all hooks for a given request, allowing you to correlate the request lifecycle. The `request_id` is also added to log records via the `extra` field, so you can filter logs by request.

## OpenTelemetry Integration

The token-based instrumentation interface is designed specifically to work well with OpenTelemetry. Here's a complete example:

```python
from typing import Any
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from mcp.types import RequestId

class OpenTelemetryInstrumenter:
    """OpenTelemetry implementation of the MCP Instrumenter protocol."""
    
    def __init__(self, tracer_provider=None):
        if tracer_provider is None:
            tracer_provider = trace.get_tracer_provider()
        self.tracer = tracer_provider.get_tracer("mcp.sdk", version="1.0.0")
    
    def on_request_start(
        self,
        request_id: RequestId,
        request_type: str,
        method: str | None = None,
        **metadata: Any,
    ) -> Any:
        """Start a new span and return it as the token."""
        span_name = f"mcp.{request_type}"
        if method:
            span_name = f"{span_name}.{method}"
        
        # Start the span
        span = self.tracer.start_span(span_name)
        
        # Set attributes
        span.set_attribute("mcp.request_id", str(request_id))
        span.set_attribute("mcp.request_type", request_type)
        if method:
            span.set_attribute("mcp.method", method)
        
        # Add metadata
        session_type = metadata.get("session_type")
        if session_type:
            span.set_attribute("mcp.session_type", session_type)
        
        # Return span as token
        return span
    
    def on_request_end(
        self,
        token: Any,  # This is the span from on_request_start
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        """End the span."""
        if token is None:
            return
        
        span = token
        
        # Set success attributes
        span.set_attribute("mcp.success", success)
        if duration_seconds is not None:
            span.set_attribute("mcp.duration_seconds", duration_seconds)
        
        # Set status
        if success:
            span.set_status(Status(StatusCode.OK))
        else:
            span.set_status(Status(StatusCode.ERROR))
            error_msg = metadata.get("error")
            if error_msg:
                span.set_attribute("mcp.error", str(error_msg))
        
        # End the span
        span.end()
    
    def on_error(
        self,
        token: Any,  # This is the span from on_request_start
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata: Any,
    ) -> None:
        """Record error in the span."""
        if token is None:
            return
        
        span = token
        
        # Record exception
        span.record_exception(error)
        span.set_attribute("mcp.error_type", error_type)
        span.set_attribute("mcp.error_message", str(error))
        
        # Set error status
        span.set_status(Status(StatusCode.ERROR, str(error)))
```

### Full Working Example

A complete working example with OpenTelemetry setup is available in `examples/opentelemetry_instrumentation.py`.

To use it:

```bash
# Install OpenTelemetry
pip install opentelemetry-api opentelemetry-sdk

# Run the example
python examples/opentelemetry_instrumentation.py
```

### Key Benefits

The token-based design provides several advantages for OpenTelemetry:

1. **No external storage**: No need to maintain a `spans` dictionary
2. **Automatic cleanup**: Spans are garbage collected when done
3. **Thread-safe**: Each request gets its own token
4. **Context propagation**: Easy to integrate with OpenTelemetry context
5. **Distributed tracing**: Can be extended to propagate trace context in `_meta`

## Default Behavior

If no instrumenter is provided, a no-op implementation is used automatically. This has minimal overhead and doesn't affect request processing.

```python
from mcp.shared.instrumentation import get_default_instrumenter

# Get the default no-op instrumenter
instrumenter = get_default_instrumenter()
```

## Best Practices

1. **Keep hooks fast**: Instrumentation hooks are called synchronously in the request path. Keep processing minimal to avoid impacting request latency.

2. **Handle errors gracefully**: Exceptions in instrumentation hooks are caught and logged, but it's best to handle errors within your instrumenter.

3. **Use appropriate metadata**: Include relevant context in metadata fields to aid debugging and analysis.

4. **Consider sampling**: For high-volume servers, consider implementing sampling in your instrumenter to reduce overhead.

## Example: Custom Metrics

```python
from collections import defaultdict
from typing import Any, Dict
from mcp.types import RequestId

class MetricsInstrumenter:
    """Track request counts and durations."""
    
    def __init__(self):
        self.request_counts: Dict[str, int] = defaultdict(int)
        self.request_durations: Dict[str, list[float]] = defaultdict(list)
        self.error_counts: Dict[str, int] = defaultdict(int)
    
    def on_request_start(
        self,
        request_id: RequestId,
        request_type: str,
        method: str | None = None,
        **metadata: Any,
    ) -> Any:
        """Track request start, return request_type as token."""
        self.request_counts[request_type] += 1
        return request_type  # Simple token - just the request type
    
    def on_request_end(
        self,
        token: Any,
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        """Track request completion."""
        if duration_seconds is not None:
            self.request_durations[request_type].append(duration_seconds)
    
    def on_error(
        self,
        token: Any,
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata: Any,
    ) -> None:
        """Track errors."""
        self.error_counts[error_type] += 1
    
    def get_stats(self):
        """Get statistics summary."""
        stats = {}
        for request_type, durations in self.request_durations.items():
            if durations:
                avg_duration = sum(durations) / len(durations)
                stats[request_type] = {
                    "count": self.request_counts[request_type],
                    "avg_duration": avg_duration,
                }
        return stats
```

Note: For this simple metrics case, the token isn't strictly necessary, so we just return the `request_type`. For more complex instrumenters (like OpenTelemetry), the token is essential for maintaining state.

## Future Work

- Package OpenTelemetry instrumenter as a separate installable extra (`pip install mcp[opentelemetry]`)
- Additional built-in instrumenters (Prometheus, StatsD, Datadog, etc.)
- Support for distributed tracing via `params._meta.traceparent` propagation (see [modelcontextprotocol/spec#414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414))
- Semantic conventions for MCP traces and metrics (see [open-telemetry/semantic-conventions#2083](https://github.com/open-telemetry/semantic-conventions/pull/2083))
- Client-side request instrumentation
- Async hook support for long-running instrumentation operations
