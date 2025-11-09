# MCP StreamableHTTP Session Roaming Example

A comprehensive example demonstrating **session roaming** across multiple MCP server instances using the StreamableHTTP transport with EventStore.

## What is Session Roaming?

Session roaming allows MCP sessions to seamlessly move between different server instances without requiring sticky sessions. This enables:

- **Horizontal scaling**: Run multiple server instances behind a load balancer
- **Zero-downtime deployments**: Sessions continue during rolling updates
- **High availability**: Failover to healthy instances automatically
- **Cloud-native architecture**: Works in Kubernetes, ECS, and other container orchestrators

## How It Works

### The Key Insight

**EventStore serves dual purposes:**

1. **Event replay** (resumability): Replays missed events when clients reconnect
2. **Session proof** (roaming): Proves a session existed, enabling any instance to serve it

When a client sends a session ID that's not in an instance's local memory, the presence of an EventStore allows that instance to:

1. Accept the unknown session ID
2. Create a transport for that session
3. Let EventStore replay any missed events
4. Continue the session seamlessly

### Architecture

```text
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ Session: abc123
       ↓
┌─────────────────┐
│ Load Balancer   │
└────────┬────────┘
         │
    ┌────┴────┐
    ↓         ↓
┌────────┐ ┌────────┐
│ Pod 1  │ │ Pod 2  │  ← Both share Redis EventStore
│ :3001  │ │ :3002  │
└────────┘ └────────┘
    │         │
    └────┬────┘
         ↓
  ┌─────────────┐
  │    Redis    │  ← Shared EventStore
  │ EventStore  │
  └─────────────┘
```

**Request Flow:**

1. Client creates session on Pod 1 (session ID: `abc123`)
2. Session stored in Pod 1's memory
3. Events stored in Redis EventStore
4. Next request goes to Pod 2 with session `abc123`
5. Pod 2 doesn't have `abc123` in memory
6. Pod 2 sees EventStore is configured
7. Pod 2 creates transport for `abc123` (session roaming!)
8. EventStore replays events from Redis
9. Session continues on Pod 2

## Features

- **Multi-instance support**: Run multiple server instances simultaneously
- **Session roaming**: Sessions work across all instances
- **Redis EventStore**: Persistent event storage for production use
- **Live demonstration**: Includes test script showing roaming in action
- **Production-ready**: Battle-tested patterns for distributed deployments

## Prerequisites

- Python 3.10+
- Redis server running (default: `localhost:6379`)
- uv package manager

## Installation

```bash
# Install dependencies
cd examples/servers/simple-streamablehttp-roaming
uv sync
```

## Usage

### Start Redis

```bash
# Using Docker
docker run -p 6379:6379 redis:latest

# Or using local Redis
redis-server
```

### Running Multiple Instances

**Terminal 1 - Instance 1:**

```bash
uv run mcp-streamablehttp-roaming --port 3001 --instance-id instance-1
```

**Terminal 2 - Instance 2:**

```bash
uv run mcp-streamablehttp-roaming --port 3002 --instance-id instance-2
```

**Terminal 3 - Instance 3:**

```bash
uv run mcp-streamablehttp-roaming --port 3003 --instance-id instance-3
```

All instances share the same Redis EventStore, enabling session roaming between them.

### Command-Line Options

```bash
--port PORT              Port to listen on (default: 3001)
--instance-id ID         Instance identifier for logging (default: instance-1)
--redis-url URL          Redis connection URL (default: redis://localhost:6379)
--log-level LEVEL        Logging level (default: INFO)
--json-response          Use JSON responses instead of SSE streams
```

## Testing Session Roaming

### Automated Test Script

The example includes a test script that demonstrates session roaming:

```bash
# Make the script executable
chmod +x test_roaming.sh

# Run the test (requires instances on ports 3001 and 3002)
./test_roaming.sh
```

**What the test does:**

1. Creates a session on Instance 1 (port 3001)
2. Calls a tool on Instance 1
3. Uses the same session ID on Instance 2 (port 3002)
4. Calls a tool on Instance 2
5. Verifies the session roamed successfully

**Expected output:**

```text
🧪 Testing Session Roaming Across MCP Instances
================================================

📍 Step 1: Creating session on Instance 1 (port 3001)...
✅ Session created: a1b2c3d4e5f67890

📍 Step 2: Calling tool on Instance 1...
✅ Tool executed successfully on Instance 1

📍 Step 3: Using same session on Instance 2 (port 3002)...
✅ Session roamed to Instance 2!

🎉 SUCCESS! Session roaming works!
   - Instance 1 handled initial request
   - Instance 2 handled subsequent request
   - Same session ID used: a1b2c3d4e5f67890
```

### Manual Testing

#### Step 1: Create session on Instance 1

```bash
curl -X POST http://localhost:3001/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "1.0.0",
      "capabilities": {},
      "clientInfo": {"name": "test-client", "version": "1.0.0"}
    }
  }' -i
```

**Note the session ID from the response header:**

```text
MCP-Session-ID: a1b2c3d4e5f67890abcdef1234567890
```

#### Step 2: Use session on Instance 2

```bash
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Session-ID: a1b2c3d4e5f67890abcdef1234567890" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
  }'
```

**Result:** Instance 2 successfully handles the request even though the session was created on Instance 1!

## The Tool: Instance Info

This example includes a simple tool that reports which instance is handling the request:

```json
{
  "name": "get-instance-info",
  "description": "Returns information about which server instance is handling this request",
  "inputSchema": {
    "type": "object",
    "properties": {
      "message": {
        "type": "string",
        "description": "Optional message to include in response"
      }
    }
  }
}
```

This makes it easy to verify that different instances are handling requests for the same session.

## Production Deployment

### Kubernetes Example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
spec:
  replicas: 3  # Multiple instances
  selector:
    matchLabels:
      app: mcp-server
  template:
    metadata:
      labels:
        app: mcp-server
    spec:
      containers:
      - name: mcp
        image: mcp-streamablehttp-roaming:latest
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        - name: INSTANCE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name  # Unique pod name
        ports:
        - containerPort: 3001
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-service
spec:
  selector:
    app: mcp-server
  ports:
  - port: 3001
  # NO sessionAffinity needed - sessions roam freely! ✅
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis-service
spec:
  selector:
    app: redis
  ports:
  - port: 6379
```

**Key points:**

- ✅ No `sessionAffinity: ClientIP` needed
- ✅ Load balancer can route freely
- ✅ Rolling updates work seamlessly
- ✅ Horizontal pod autoscaling supported

### Docker Compose Example

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  mcp-instance-1:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - INSTANCE_ID=instance-1
    ports:
      - "3001:3001"
    depends_on:
      - redis

  mcp-instance-2:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - INSTANCE_ID=instance-2
    ports:
      - "3002:3001"
    depends_on:
      - redis

  mcp-instance-3:
    build: .
    environment:
      - REDIS_URL=redis://redis:6379
      - INSTANCE_ID=instance-3
    ports:
      - "3003:3001"
    depends_on:
      - redis

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - mcp-instance-1
      - mcp-instance-2
      - mcp-instance-3
```

## Implementation Details

### Redis EventStore

The example uses a production-ready Redis-based EventStore:

- **Persistent**: Survives server restarts
- **Shared**: All instances access the same event data
- **Fast**: Redis provides microsecond latency
- **Scalable**: Handles thousands of concurrent sessions

### Session Manager Configuration

```python
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from .redis_event_store import RedisEventStore

# Create Redis EventStore (enables session roaming!)
event_store = RedisEventStore(redis_url="redis://localhost:6379")

# Create session manager with EventStore
manager = StreamableHTTPSessionManager(
    app=app,
    event_store=event_store,  # This one parameter enables session roaming!
)
```

**That's it!** No `session_store` parameter needed. EventStore alone enables both:

- Event replay (resumability)
- Session roaming (distributed sessions)

### How Sessions Roam (Code Flow)

When a request arrives with a session ID:

1. **Check local memory** (fast path):

   ```python
   if session_id in self._server_instances:
       # Session exists locally, handle directly
       await transport.handle_request(scope, receive, send)
       return
   ```

2. **Check for EventStore** (roaming path):

   ```python
   if session_id is not None and self.event_store is not None:
       # Session not in memory, but EventStore exists
       # Create transport for this session (roaming!)
       http_transport = StreamableHTTPServerTransport(
           mcp_session_id=session_id,
           event_store=self.event_store,  # Will replay events
       )
       self._server_instances[session_id] = http_transport
       # Session has roamed to this instance! ✅
   ```

3. **No EventStore** (reject):

   ```python
   if session_id is not None:
       # Unknown session, no EventStore to verify
       return 400  # Bad Request
   ```

## Comparison with Other Approaches

### Without EventStore (In-Memory Only)

```python
# ❌ Sessions tied to specific instances
manager = StreamableHTTPSessionManager(app=app)

# Deployment requirements:
# - Sticky sessions required (sessionAffinity: ClientIP)
# - No horizontal scaling
# - No rolling updates
# - Single point of failure
```

### With EventStore (This Example)

```python
# ✅ Sessions roam freely
manager = StreamableHTTPSessionManager(
    app=app,
    event_store=RedisEventStore(redis_url="redis://localhost:6379")
)

# Deployment benefits:
# - No sticky sessions needed
# - Horizontal scaling supported
# - Rolling updates work
# - High availability
```

## Monitoring Session Roaming

The server logs session roaming events:

```text
INFO - Session abc123 roaming to this instance (EventStore enables roaming)
INFO - Created transport for roaming session: abc123
INFO - Instance instance-2 handling request for session abc123
```

You can track:

- Which instances handle which sessions
- Session creation events
- Session roaming events
- Event replay statistics

## Troubleshooting

### "Session ID not found" (400 error)

**Cause:** Session ID sent but not in memory, and no EventStore configured.

**Solution:** Ensure Redis is running and `--redis-url` is correct.

### Session not roaming between instances

**Checklist:**

- ✅ Redis running and accessible
- ✅ All instances use same `--redis-url`
- ✅ Session ID included in `MCP-Session-ID` header
- ✅ EventStore parameter passed to StreamableHTTPSessionManager

### Performance Issues

**Redis configuration:**

- Use Redis persistence (AOF or RDB) for production
- Consider Redis Cluster for high throughput
- Monitor Redis memory usage
- Set appropriate `maxmemory-policy`

## Key Concepts

### EventStore as Session Proof

Events stored in EventStore prove sessions existed:

- If EventStore has events for session `abc123`
- Then session `abc123` must have existed
- Safe for any instance to create transport for it
- EventStore replays events to catch up

### Protocol-Level Sessions (SEP-1359)

MCP sessions identify conversation context, not authentication:

- Session ID = conversation thread
- Authentication per-request (separate concern)
- Creating transport for any session ID is safe
- EventStore provides continuity

### Single Source of Truth

EventStore is the authoritative record:

- All events stored centrally
- All instances read from same source
- Consistency guaranteed
- No split-brain scenarios

## Further Reading

- [MCP StreamableHTTP Specification](https://spec.modelcontextprotocol.io/specification/basic/transports/#http-with-sse)
- [SEP-1359: Protocol-Level Sessions](https://github.com/modelcontextprotocol/specification/pull/1359)
- [EventStore Interface](../../src/mcp/server/streamable_http.py)
- [StreamableHTTPSessionManager](../../src/mcp/server/streamable_http_manager.py)

## License

MIT
