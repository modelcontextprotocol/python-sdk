# MCP gRPC: High-Performance Transport

This directory contains the Protocol Buffer definitions for the Model Context Protocol (MCP) as a native gRPC service. This implementation modernizes the MCP transport layer, moving beyond the limitations of HTTP/1.1 (lacks streaming) and JSON (type safety, memory footprint, processing speed) to provide a better foundation for AI agents.

## Why gRPC for MCP?

The traditional MCP over HTTP/1.1 uses JSON-RPC, which served as a great starting point but introduced friction as agentic workflows scaled. Our native gRPC implementation addresses these "friction points" to performance and efficiency:

```mermaid
graph LR
    subgraph "Legacy Transport (HTTP/1.1)"
        A[Client] -- "JSON (Text)" --> B[Server]
        B -- "Response" --> A
        A -. "SSE/Polling" .-> B
        style A fill:#f9f,stroke:#333,stroke-width:2px
    end
    subgraph "Modern Transport (gRPC/HTTP2)"
        C[Client] == "Protobuf (Binary)" ==> D[Server]
        C -- "Bidi Stream" --> D
        D -- "Push" --> C
        style D fill:#00ff0055,stroke:#333,stroke-width:2px
    end
```

### Key Improvements

*   **Native Bidirectional Streaming**: Replaces fragile SSE and long-polling with a single, persistent HTTP/2 stream for interleaved requests, progress updates, and server notifications.
*   **Binary Efficiency**: Protobuf serialization is typically 10x smaller and significantly faster than JSON, especially when handling large blobs or many small tool calls.
*   **Zero-Copy Intent**: By using native `bytes` for resource data, we avoid the overhead of Base64 encoding required by JSON-RPC.
*   **Native Backpressure**: Leverages HTTP/2 flow control to ensure servers aren't overwhelmed by fast clients (and vice versa).

---

## Architecture & Lifecycle

The gRPC transport is designed to be a drop-in replacement for the standard MCP session, fitting seamlessly into the pluggable transport architecture of the SDK.

### The Session Flow

Unlike traditional unary calls, a gRPC MCP session often starts with an initialization handshake and then moves into a long-lived bidirectional stream.

```mermaid
sequenceDiagram
    participant C as Client (AI Agent)
    participant S as Server (Tool Provider)
    
    Note over C,S: Connection Established (HTTP/2)
    
    C->>S: Initialize(capabilities, client_info)
    S-->>C: InitializeResponse(capabilities, server_info)
    
    rect rgb(240, 240, 240)
        Note over C,S: Persistent Session Stream
        C->>S: Session(CallToolRequest)
        S->>C: Session(ProgressNotification)
        S->>C: Session(CallToolResponse)
        Note right of S: Server discovers local file change
        S->>C: Session(ResourceChangeNotification)
    end
    
    C->>S: Ping()
    S-->>C: PingResponse()
```

---

## Service Definition

The `McpService` provides a comprehensive interface for all MCP operations. While it supports unary calls for simple operations, it excels in its streaming variants. For a deep dive into advanced patterns like document chunking and parallel worker analysis, see our [Streaming & Multiplexing Guide](../docs/experimental/grpc-streaming.md).

```protobuf
service McpService {
  // Lifecycle & Health
  rpc Initialize(InitializeRequest) returns (InitializeResponse);
  rpc Ping(PingRequest) returns (PingResponse);

  // Tools: Supports parallel execution and progress streaming
  rpc CallTool(CallToolRequest) returns (CallToolResponse);
  rpc CallToolWithProgress(...) returns (stream CallToolWithProgressResponse);

  // Resources: Efficient handling of large datasets
  rpc ReadResourceChunked(...) returns (stream ReadResourceChunkedResponse);
  rpc WatchResources(...) returns (stream WatchResourcesResponse);

  // The "Power User" Interface
  rpc Session(stream SessionRequest) returns (stream SessionResponse);
}
```

### Discoveries from Implementation

1.  **Implicit Chunking**: In our Python implementation, `read_resource` now defaults to the chunked streaming RPC under the hood. This ensures that even massive resources (like large logs or database exports) don't cause memory spikes.
2.  **Background Watchers**: Resource subscriptions are handled by background stream observers, allowing the client to receive push notifications without blocking the main event loop.
3.  **Unified Session**: The `Session` RPC acts as a multiplexer. This allows a single TCP connection to handle dozens of concurrent tool calls while simultaneously receiving resource updates.

---

## Development & Tooling

### Building the Stubs

To use this protocol in Python, you need to generate the gRPC stubs. **Note:** Due to the internal import structure of generated Protobuf files, we generate stubs into `src` which creates the appropriate package hierarchy.

```bash
# Generate Python stubs
python -m grpc_tools.protoc \
  -I proto \
  --python_out=src \
  --grpc_python_out=src \
  proto/mcp/v1/mcp.proto

# This creates:
# src/mcp/v1/mcp_pb2.py        (Standard messages)
# src/mcp/v1/mcp_pb2_grpc.py   (gRPC client/server stubs)
```

### Dependencies

Ensure your environment has the necessary gRPC libraries:

```bash
uv add grpcio grpcio-tools
```

---

## Status

**Current Status:** `Alpha / Experiemental / RFC`

The core protocol is stable and implemented in the Python SDK's `GrpcClientTransport`. We are actively seeking feedback on the `Session` stream multiplexing patterns before finalizing the V1 specification.

## References

- [Official MCP Website](https://modelcontextprotocol.io)
- [Original gRPC Proposal](https://cloud.google.com/blog/products/networking/grpc-as-a-native-transport-for-mcp)
- [gRPC Documentation](https://grpc.io/docs/)

## Open Questions



### Pagination vs. Streaming vs. Limits



In HTTP/JSON-RPC, paginating large lists (like `ListTools` or `ListResources`) is standard practice to manage payload sizes. gRPC offers native streaming (`stream Tool`), which allows the server to yield items one by one.



**Design Decision:** We have opted for **Streaming** over Pagination in the V1 gRPC definitions.

- **Pros:** Simpler API (no cursors), lower latency (process items as they arrive), no "page size" guessing.

- **Cons:** "Give me just the first 10" requires the client to explicitly close the stream after 10 items.



**Question:** Should we add an optional `limit` field to Request messages to allow the server to stop generating early, optimizing server-side work? Or rely on client cancellation?

### ClientStreamingTransportSession Interface

The current `ClientTransportSession` interface returns complete results (e.g., `ListToolsResult` with a full list). For gRPC, this means buffering the entire stream into memory before returning, which works but loses the memory efficiency benefits of streaming.

**Proposed:** Add a `ClientStreamingTransportSession` interface that extends `ClientTransportSession`:

```python
class ClientTransportSession(ABC):
    # Existing - returns complete results (backward compat)
    async def list_tools(...) -> ListToolsResult

class ClientStreamingTransportSession(ClientTransportSession):
    # Adds streaming variants
    def stream_list_tools(self) -> AsyncIterator[Tool]
    def stream_list_resources(self) -> AsyncIterator[Resource]
    def stream_list_prompts(self) -> AsyncIterator[Prompt]
    async def call_tool_with_progress(...) -> AsyncIterator[ProgressNotification | ToolResult]
```

**Benefits:**
- gRPC transport implements both - callers choose based on their needs
- `list_tools()` for simple use cases, `stream_list_tools()` for memory-efficient processing
- Existing code using `ClientTransportSession` continues to work unchanged
- HTTP/JSON-RPC transports implement only the base interface

**Question:** Is this the right abstraction? Should streaming be opt-in via a separate interface, or should we change the base interface to always return iterators?

## Implementation Notes



### True Streaming vs. Buffering



While the gRPC transport layer fully supports streaming (yielding `ListToolsResponse` or `ReadResourceChunkedResponse` messages individually), the current Python SDK `Server` implementation primarily operates with buffered lists.



*   **List Operations:** Handlers for `list_tools`, `list_resources`, etc., typically return a full `list[...]`. The gRPC transport iterates over this list to stream responses, meaning the latency benefit is "transport-only" rather than "end-to-end" until the core `Server` supports async generators.

*   **Resource Reading:** Similarly, `read_resource` handlers currently return the complete content. The gRPC transport chunks this content *after* it has been fully loaded into memory. True zero-copy streaming from disk/network to the gRPC stream will require updates to the `Server` class to support yielding data chunks directly.
