# File Structure

This example demonstrates session roaming across multiple MCP server instances.

## Directory Structure

```text
simple-streamablehttp-roaming/
├── README.md                              # Comprehensive documentation
├── QUICKSTART.md                          # 5-minute getting started guide
├── FILES.md                               # This file
├── pyproject.toml                         # Project configuration
├── Dockerfile                             # Docker container definition
├── docker-compose.yml                     # Multi-instance deployment
├── nginx.conf                             # Load balancer configuration
├── test_roaming.sh                        # Automated test script
├── .gitignore                             # Git ignore patterns
└── mcp_simple_streamablehttp_roaming/
    ├── __init__.py                        # Package initialization
    ├── __main__.py                        # Module entry point
    ├── server.py                          # Main server implementation
    └── redis_event_store.py               # Redis EventStore implementation

```

## File Purposes

### Documentation

- **README.md** (486 lines)
  - Comprehensive guide to session roaming
  - Architecture diagrams and explanations
  - Production deployment examples (Kubernetes, Docker Compose)
  - Testing instructions
  - Implementation details

- **QUICKSTART.md** (381 lines)
  - Get started in 5 minutes
  - Step-by-step local development setup
  - Docker Compose deployment guide
  - Manual testing examples
  - Common issues and solutions

- **FILES.md** (This file)
  - Overview of file structure
  - Purpose of each file

### Python Package

- **mcp_simple_streamablehttp_roaming/**init**.py** (3 lines)
  - Package version information

- **mcp_simple_streamablehttp_roaming/**main**.py** (5 lines)
  - Entry point for running as module

- **mcp_simple_streamablehttp_roaming/server.py** (169 lines)
  - Main MCP server implementation
  - Command-line interface
  - Tool: `get-instance-info` (shows which instance handles request)
  - Session manager configuration with EventStore
  - Starlette ASGI application

- **mcp_simple_streamablehttp_roaming/redis_event_store.py** (154 lines)
  - Production-ready Redis EventStore implementation
  - Persistent event storage
  - Event replay functionality
  - Shared across all instances

### Configuration

- **pyproject.toml** (44 lines)
  - Project metadata
  - Dependencies (mcp, redis, starlette, uvicorn, etc.)
  - CLI script registration
  - Build configuration
  - Development tools (pyright, pytest, ruff)

- **.gitignore** (35 lines)
  - Python artifacts
  - Virtual environments
  - IDE files
  - Cache directories

### Deployment

- **Dockerfile** (20 lines)
  - Multi-stage Python container
  - Uses uv for dependency management
  - Optimized for production

- **docker-compose.yml** (85 lines)
  - Redis service (persistent event store)
  - 3 MCP server instances (ports 3001, 3002, 3003)
  - NGINX load balancer (port 80)
  - Health checks and dependencies
  - Volume management

- **nginx.conf** (60 lines)
  - Round-robin load balancing (NO sticky sessions!)
  - SSE support configuration
  - CORS headers
  - MCP-Session-ID header pass-through
  - Health check endpoint

### Testing

- **test_roaming.sh** (100 lines)
  - Automated test script
  - Creates session on Instance 1
  - Calls tool on Instance 1
  - Uses same session on Instance 2
  - Verifies session roaming works
  - Detailed success/failure reporting

## Key Features Demonstrated

### 1. Session Roaming

- Sessions move freely between instances
- No sticky sessions required
- EventStore provides continuity

### 2. Production Deployment

- Docker Compose for local testing
- Kubernetes manifests in README
- NGINX load balancing example
- Redis persistence configuration

### 3. Developer Experience

- Automated testing script
- Comprehensive documentation
- Quick start guide
- Clear error messages
- Detailed logging

### 4. Code Quality

- Type hints throughout
- Comprehensive docstrings
- Configuration via CLI arguments
- Environment-based configuration
- Proper error handling

## Usage Examples

### Local Development

```bash
# Terminal 1
uv run mcp-streamablehttp-roaming --port 3001 --instance-id instance-1

# Terminal 2
uv run mcp-streamablehttp-roaming --port 3002 --instance-id instance-2

# Terminal 3
./test_roaming.sh
```

### Docker Compose

```bash
docker-compose up -d
# Access via http://localhost/mcp (load balanced)
# or directly via http://localhost:3001/mcp, :3002/mcp, :3003/mcp
```

### Manual Testing

```bash
# Create session on Instance 1
curl -X POST http://localhost:3001/mcp -H "Content-Type: application/json" ...

# Use session on Instance 2
curl -X POST http://localhost:3002/mcp -H "MCP-Session-ID: <session-id>" ...
```

## Total Lines of Code

- Python code: ~331 lines
- Configuration: ~149 lines
- Documentation: ~867 lines
- Testing: ~100 lines
- **Total: ~1,447 lines**

## Implementation Highlights

### Minimal Code for Maximum Impact

**Enable session roaming with just:**

```python
event_store = RedisEventStore(redis_url="redis://localhost:6379")
manager = StreamableHTTPSessionManager(app=app, event_store=event_store)
```

### No Special Session Store Needed

The EventStore alone enables:

- ✅ Event replay (resumability)
- ✅ Session roaming (distributed sessions)
- ✅ Horizontal scaling
- ✅ High availability

### Production-Ready Patterns

- Redis persistence (AOF enabled)
- Health checks
- Graceful shutdown
- Comprehensive logging
- Environment-based configuration
- CORS support

## Related Files in SDK

The example uses these SDK components:

- `mcp.server.streamable_http_manager.StreamableHTTPSessionManager` - Session management
- `mcp.server.streamable_http.EventStore` - Interface for event storage
- `mcp.server.lowlevel.Server` - Core MCP server
- `mcp.types` - MCP protocol types

## Contributing

To extend this example:

1. **Add new tools** - Modify `server.py` to add more tool handlers
2. **Custom EventStore** - Implement EventStore for other databases
3. **Monitoring** - Add Prometheus metrics or OpenTelemetry
4. **Authentication** - Add auth middleware to Starlette app
5. **Rate limiting** - Add rate limiting middleware

See README.md for more details on each approach.
