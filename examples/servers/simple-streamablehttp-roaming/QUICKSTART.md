# Quick Start Guide - Session Roaming

Get up and running with session roaming in 5 minutes!

## Prerequisites

- Python 3.10+
- uv package manager
- Redis (or Docker for Redis)

## Option 1: Local Development (Recommended for Learning)

### Step 1: Start Redis

**Using Docker:**

```bash
docker run -d -p 6379:6379 redis:latest
```

**Or using local Redis:**

```bash
redis-server
```

### Step 2: Install Dependencies

```bash
cd examples/servers/simple-streamablehttp-roaming
uv sync
```

### Step 3: Start Multiple Instances

**Terminal 1 - Instance 1:**

```bash
uv run mcp-streamablehttp-roaming --port 3001 --instance-id instance-1
```

**Terminal 2 - Instance 2:**

```bash
uv run mcp-streamablehttp-roaming --port 3002 --instance-id instance-2
```

You should see:

```text
======================================================================
🚀 Instance instance-1 started with SESSION ROAMING!
======================================================================
✓ Redis EventStore enables session roaming across instances
✓ Sessions can move between any server instance
✓ No sticky sessions required!
✓ Horizontal scaling supported
======================================================================
```

### Step 4: Test Session Roaming

**Terminal 3 - Run Test:**

```bash
./test_roaming.sh
```

Expected output:

```text
🧪 Testing Session Roaming Across MCP Instances
================================================

✅ Both instances are running

📍 Step 1: Creating session on Instance 1 (port 3001)...
✅ Session created: a1b2c3d4e5f67890

📍 Step 2: Calling tool on Instance 1...
✅ Tool executed successfully on Instance 1

📍 Step 3: Using same session on Instance 2 (port 3002)...
✅ Session roamed to Instance 2!

🎉 SUCCESS! Session roaming works!
```

**What just happened?**

1. Session created on Instance 1
2. Tool called on Instance 1 - success
3. **Same session** used on Instance 2 - **also success!**
4. Session "roamed" from Instance 1 to Instance 2

## Option 2: Docker Compose (Production-Like)

### Step 1: Build and Start

```bash
cd examples/servers/simple-streamablehttp-roaming
docker-compose up -d
```

This starts:

- Redis (persistent event store)
- 3 MCP server instances (ports 3001, 3002, 3003)
- NGINX load balancer (port 80)

### Step 2: Test Through Load Balancer

```bash
# Create session (will go to random instance)
curl -X POST http://localhost/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "1.0.0",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }' -i

# Note the MCP-Session-ID from response headers
# Use it in subsequent requests - they may go to different instances!

curl -X POST http://localhost/mcp \
  -H "Content-Type: application/json" \
  -H "MCP-Session-ID: <your-session-id>" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get-instance-info",
      "arguments": {}
    }
  }'
```

Each request may be handled by a different instance, but the session continues seamlessly!

### Step 3: View Logs

```bash
# See which instances handle requests
docker-compose logs -f mcp-instance-1
docker-compose logs -f mcp-instance-2
docker-compose logs -f mcp-instance-3
```

Look for these log messages:

```text
INFO - Session abc123 roaming to this instance (EventStore enables roaming)
INFO - Created transport for roaming session: abc123
INFO - Instance instance-2 handling request for session abc123
```

### Step 4: Cleanup

```bash
docker-compose down -v
```

## Manual Testing Guide

### Create a Session

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

**Save the session ID from the response header:**

```text
MCP-Session-ID: a1b2c3d4e5f67890abcdef1234567890
```

### Call Tool on Instance 1

```bash
curl -X POST http://localhost:3001/mcp \
  -H "Content-Type: application/json" \
  -H "MCP-Session-ID: a1b2c3d4e5f67890abcdef1234567890" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "get-instance-info",
      "arguments": {
        "message": "Hello from Instance 1"
      }
    }
  }'
```

**Response shows:**

```json
{
  "result": {
    "content": [{
      "type": "text",
      "text": "Instance: instance-1\nPort: 3001\n..."
    }]
  }
}
```

### Call Tool on Instance 2 (Same Session!)

```bash
curl -X POST http://localhost:3002/mcp \
  -H "Content-Type: application/json" \
  -H "MCP-Session-ID: a1b2c3d4e5f67890abcdef1234567890" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "get-instance-info",
      "arguments": {
        "message": "Hello from Instance 2 - session roamed!"
      }
    }
  }'
```

**Response shows:**

```json
{
  "result": {
    "content": [{
      "type": "text",
      "text": "Instance: instance-2\nPort: 3002\n..."
    }]
  }
}
```

**✅ Success!** Same session ID, different instances!

## Understanding the Magic

### What Enables Session Roaming?

**Just one line of code:**

```python
session_manager = StreamableHTTPSessionManager(
    app=app,
    event_store=RedisEventStore(redis_url="redis://localhost:6379")
)
```

That's it! The `event_store` parameter enables:

1. ✅ Event replay (resumability)
2. ✅ Session roaming (distributed sessions)

### How Does It Work?

When Instance 2 receives a request with an unknown session ID:

1. **Checks local memory** - session not found
2. **Checks for EventStore** - Redis EventStore exists
3. **Creates transport for session** - session roams! 🎉
4. **EventStore replays events** - session catches up
5. **Request succeeds** - seamless experience

### Why Does This Work?

Events in EventStore prove sessions existed:

- Session `abc123` has events in Redis
- Therefore session `abc123` existed
- Safe to create transport for it
- EventStore provides continuity

## Common Issues

### "Connection refused" on port 6379

**Problem:** Redis not running

**Solution:**

```bash
docker run -d -p 6379:6379 redis:latest
```

### "Session ID not found" (400 error)

**Problem:** EventStore not configured or Redis not accessible

**Solution:**

- Check Redis is running: `redis-cli ping` (should return "PONG")
- Check Redis URL in server startup
- Check logs for Redis connection errors

### Session not roaming

**Checklist:**

- [ ] Redis running and accessible
- [ ] All instances use same `--redis-url`
- [ ] Session ID included in `MCP-Session-ID` header
- [ ] EventStore configured in code

## Next Steps

1. **Read the full README** for architecture details
2. **Try with 3+ instances** to see round-robin load balancing
3. **Implement your own EventStore** (PostgreSQL, DynamoDB, etc.)
4. **Deploy to Kubernetes** using the example manifests

## Questions?

Check out:

- [README.md](README.md) - Full documentation
- [server.py](mcp_simple_streamablehttp_roaming/server.py) - Implementation
- [redis_event_store.py](mcp_simple_streamablehttp_roaming/redis_event_store.py) - EventStore implementation

Happy roaming! 🚀
