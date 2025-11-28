# Instrumentation

The MCP Python SDK provides a pluggable instrumentation interface for monitoring request/response lifecycle. This enables integration with OpenTelemetry, custom metrics, logging frameworks, and other observability tools.

## Overview

The `Instrumenter` protocol defines three hooks:

- `on_request_start`: Called when a request starts processing
- `on_request_end`: Called when a request completes (successfully or not)
- `on_error`: Called when an error occurs during request processing

All methods are optional (no-op implementations are valid). Exceptions raised by instrumentation hooks are logged but do not affect request processing.

## Basic Usage

### Server-Side Instrumentation

```python
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
    ) -> None:
        print(f"Request {request_id} started: {request_type}")
    
    def on_request_end(
        self,
        request_id: RequestId,
        request_type: str,
        success: bool,
        duration_seconds: float | None = None,
        **metadata,
    ) -> None:
        status = "succeeded" if success else "failed"
        print(f"Request {request_id} {status} in {duration_seconds:.3f}s")
    
    def on_error(
        self,
        request_id: RequestId | None,
        error: Exception,
        error_type: str,
        **metadata,
    ) -> None:
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

A full OpenTelemetry instrumenter will be provided in a future release or as a separate package. Here's a basic example to get started:

```python
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer(__name__)

class OpenTelemetryInstrumenter:
    def __init__(self):
        self.spans = {}
    
    def on_request_start(self, request_id, request_type, **metadata):
        span = tracer.start_span(
            f"mcp.request.{request_type}",
            attributes={
                "mcp.request_id": str(request_id),
                "mcp.request_type": request_type,
                **metadata,
            }
        )
        self.spans[request_id] = span
    
    def on_request_end(self, request_id, request_type, success, duration_seconds=None, **metadata):
        if span := self.spans.pop(request_id, None):
            if duration_seconds:
                span.set_attribute("mcp.duration_seconds", duration_seconds)
            span.set_status(Status(StatusCode.OK if success else StatusCode.ERROR))
            span.end()
    
    def on_error(self, request_id, error, error_type, **metadata):
        if span := self.spans.get(request_id):
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
```

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
from typing import Dict

class MetricsInstrumenter:
    """Track request counts and durations."""
    
    def __init__(self):
        self.request_counts: Dict[str, int] = defaultdict(int)
        self.request_durations: Dict[str, list[float]] = defaultdict(list)
        self.error_counts: Dict[str, int] = defaultdict(int)
    
    def on_request_start(self, request_id, request_type, **metadata):
        self.request_counts[request_type] += 1
    
    def on_request_end(self, request_id, request_type, success, duration_seconds=None, **metadata):
        if duration_seconds is not None:
            self.request_durations[request_type].append(duration_seconds)
    
    def on_error(self, request_id, error, error_type, **metadata):
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

## Future Work

- Full OpenTelemetry integration as a separate module
- Additional built-in instrumenters (Prometheus, StatsD, etc.)
- Client-side request instrumentation
- Async hook support for long-running instrumentation operations

