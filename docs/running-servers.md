# Running servers

Learn the different ways to run your MCP servers: development mode with the MCP Inspector, integration with Claude Desktop, direct execution, and production deployment.

## Development mode

### MCP Inspector

The fastest way to test and debug your server is with the built-in MCP Inspector:

```bash
# Basic usage
uv run mcp dev server.py

# With additional dependencies
uv run mcp dev server.py --with pandas --with numpy

# Mount local code as editable
uv run mcp dev server.py --with-editable .

# Custom port
uv run mcp dev server.py --port 8001
```

The MCP Inspector provides:

- **Interactive web interface** - Test tools, resources, and prompts
- **Real-time logging** - See all server logs and debug information  
- **Request/response inspection** - Debug MCP protocol messages
- **Auto-reload** - Automatically restart when code changes
- **Dependency management** - Install packages on-the-fly

### Development server example

```python
\"\"\"
Development server with comprehensive features.

Run with: uv run mcp dev development_server.py
\"\"\"

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

# Create server with debug settings
mcp = FastMCP(
    \"Development Server\",
    debug=True,
    log_level=\"DEBUG\"
)

@mcp.tool()
async def debug_info(ctx: Context[ServerSession, None]) -> dict:
    \"\"\"Get debug information about the server and request.\"\"\"
    await ctx.debug(\"Debug info requested\")
    
    return {
        \"server\": {
            \"name\": ctx.fastmcp.name,
            \"debug_mode\": ctx.fastmcp.settings.debug,
            \"log_level\": ctx.fastmcp.settings.log_level
        },
        \"request\": {
            \"request_id\": ctx.request_id,
            \"client_id\": ctx.client_id
        }
    }

@mcp.resource(\"dev://logs/{level}\")
def get_logs(level: str) -> str:
    \"\"\"Get simulated log entries for development.\"\"\"
    logs = {
        \"info\": \"2024-01-01 10:00:00 INFO: Server started\\n2024-01-01 10:01:00 INFO: Client connected\",
        \"debug\": \"2024-01-01 10:00:00 DEBUG: Initializing server\\n2024-01-01 10:00:01 DEBUG: Loading configuration\",
        \"error\": \"2024-01-01 10:02:00 ERROR: Failed to process request\\n2024-01-01 10:02:01 ERROR: Database connection lost\"
    }
    return logs.get(level, \"No logs found for level: \" + level)

if __name__ == \"__main__\":
    # Run with development settings
    mcp.run()
```

## Claude Desktop integration

### Installing servers

Install your server in Claude Desktop for production use:

```bash
# Basic installation
uv run mcp install server.py

# Custom server name
uv run mcp install server.py --name \"My Analytics Server\"

# With environment variables
uv run mcp install server.py -v API_KEY=abc123 -v DB_URL=postgres://localhost/myapp

# From environment file
uv run mcp install server.py -f .env

# Specify custom port
uv run mcp install server.py --port 8080
```

### Example production server

```python
\"\"\"
Production-ready MCP server for Claude Desktop.

Install with: uv run mcp install production_server.py --name \"Analytics Server\"
\"\"\"

import os
from mcp.server.fastmcp import FastMCP

# Create production server
mcp = FastMCP(
    \"Analytics Server\",
    instructions=\"Provides data analytics and business intelligence tools\",
    debug=False,  # Disable debug mode for production
    log_level=\"INFO\"
)

@mcp.tool()
def calculate_metrics(data: list[float]) -> dict[str, float]:
    \"\"\"Calculate key metrics from numerical data.\"\"\"
    if not data:
        raise ValueError(\"Data cannot be empty\")
    
    return {
        \"count\": len(data),
        \"mean\": sum(data) / len(data),
        \"min\": min(data),
        \"max\": max(data),
        \"sum\": sum(data)
    }

@mcp.resource(\"config://database\")
def get_database_config() -> str:
    \"\"\"Get database configuration from environment.\"\"\"
    db_url = os.getenv(\"DB_URL\", \"sqlite:///default.db\")
    return f\"Database URL: {db_url}\"

@mcp.prompt()
def analyze_data(dataset_name: str, analysis_type: str = \"summary\") -> str:
    \"\"\"Generate data analysis prompt.\"\"\"
    return f\"\"\"Please analyze the {dataset_name} dataset.

Analysis type: {analysis_type}

Provide:
1. Key insights and trends
2. Notable patterns or anomalies  
3. Actionable recommendations
4. Data quality assessment
\"\"\"

if __name__ == \"__main__\":
    mcp.run()
```

### Environment configuration

Create a `.env` file for environment variables:

```bash
# .env file for MCP server
DB_URL=postgresql://user:pass@localhost/analytics
API_KEY=your-secret-api-key
REDIS_URL=redis://localhost:6379/0
LOG_LEVEL=INFO
DEBUG_MODE=false
```

## Direct execution

### Simple execution

Run servers directly for custom deployments:

```python
\"\"\"
Direct execution example.

Run with: python direct_server.py
\"\"\"

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(\"Direct Server\")

@mcp.tool()
def hello(name: str = \"World\") -> str:
    \"\"\"Say hello to someone.\"\"\"
    return f\"Hello, {name}!\"

def main():
    \"\"\"Entry point for direct execution.\"\"\"
    # Run with default transport (stdio)
    mcp.run()

if __name__ == \"__main__\":
    main()
```

### Command-line arguments

Add CLI support for flexible execution:

```python
\"\"\"
Server with command-line interface.

Run with: python cli_server.py --port 8080 --debug
\"\"\"

import argparse
from mcp.server.fastmcp import FastMCP

def create_server(debug: bool = False, log_level: str = \"INFO\") -> FastMCP:
    \"\"\"Create server with configuration.\"\"\"
    return FastMCP(
        \"CLI Server\",
        debug=debug,
        log_level=log_level
    )

def main():
    \"\"\"Main entry point with argument parsing.\"\"\"
    parser = argparse.ArgumentParser(description=\"MCP Server with CLI\")
    parser.add_argument(\"--port\", type=int, default=8000, help=\"Server port\")
    parser.add_argument(\"--host\", default=\"localhost\", help=\"Server host\")
    parser.add_argument(\"--debug\", action=\"store_true\", help=\"Enable debug mode\")
    parser.add_argument(\"--log-level\", choices=[\"DEBUG\", \"INFO\", \"WARNING\", \"ERROR\"], 
                       default=\"INFO\", help=\"Log level\")
    parser.add_argument(\"--transport\", choices=[\"stdio\", \"sse\", \"streamable-http\"],
                       default=\"stdio\", help=\"Transport type\")
    
    args = parser.parse_args()
    
    # Create server with parsed arguments
    mcp = create_server(debug=args.debug, log_level=args.log_level)
    
    @mcp.tool()
    def get_server_config() -> dict:
        \"\"\"Get current server configuration.\"\"\"
        return {
            \"host\": args.host,
            \"port\": args.port,
            \"debug\": args.debug,
            \"log_level\": args.log_level,
            \"transport\": args.transport
        }
    
    # Run with specified configuration
    mcp.run(
        transport=args.transport,
        host=args.host,
        port=args.port
    )

if __name__ == \"__main__\":
    main()
```

## Transport options

### stdio transport (default)

Best for Claude Desktop integration and command-line tools:

```python
# Run with stdio (default)
mcp.run()  # or mcp.run(transport=\"stdio\")
```

### HTTP transports

#### SSE (Server-Sent Events)

```python
# Run with SSE transport
mcp.run(transport=\"sse\", host=\"0.0.0.0\", port=8000)
```

#### Streamable HTTP (recommended for production)

```python
# Run with Streamable HTTP transport
mcp.run(transport=\"streamable-http\", host=\"0.0.0.0\", port=8000)

# With stateless configuration (better for scaling)
mcp = FastMCP(\"Stateless Server\", stateless_http=True)
mcp.run(transport=\"streamable-http\")
```

### Transport comparison

| Transport | Best for | Pros | Cons |
|-----------|----------|------|------|
| **stdio** | Claude Desktop, CLI tools | Simple, reliable | Not web-accessible |
| **SSE** | Web integration, streaming | Real-time updates | Being superseded |
| **Streamable HTTP** | Production, scaling | Stateful/stateless, resumable | More complex |

## Production deployment

### Docker deployment

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ src/

# Install dependencies
RUN uv sync --frozen

# Copy server code
COPY server.py .

# Expose port
EXPOSE 8000

# Run server
CMD [\"uv\", \"run\", \"python\", \"server.py\", \"--transport\", \"streamable-http\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]
```

Build and run:

```bash
# Build image
docker build -t my-mcp-server .

# Run container
docker run -p 8000:8000 -e API_KEY=secret my-mcp-server
```

### Docker Compose

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  mcp-server:
    build: .
    ports:
      - \"8000:8000\"
    environment:
      - API_KEY=${API_KEY}
      - DB_URL=postgresql://postgres:password@db:5432/myapp
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    restart: unless-stopped

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

volumes:
  postgres_data:
```

### Process management with systemd

Create `/etc/systemd/system/mcp-server.service`:

```ini
[Unit]
Description=MCP Server
After=network.target

[Service]
Type=simple
User=mcp
WorkingDirectory=/opt/mcp-server
ExecStart=/opt/mcp-server/.venv/bin/python server.py --transport streamable-http --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PATH=/opt/mcp-server/.venv/bin
EnvironmentFile=/opt/mcp-server/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable mcp-server
sudo systemctl start mcp-server
sudo systemctl status mcp-server
```

### Reverse proxy with nginx

Create `/etc/nginx/sites-available/mcp-server`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection \"upgrade\";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # For Server-Sent Events
        proxy_buffering off;
        proxy_cache off;
    }
}
```

## Monitoring and health checks

### Health check endpoint

```python
@mcp.tool()
async def health_check() -> dict:
    \"\"\"Server health check endpoint.\"\"\"
    import time
    import psutil
    
    return {
        \"status\": \"healthy\",
        \"timestamp\": time.time(),
        \"uptime\": time.time() - server_start_time,
        \"memory_usage\": psutil.Process().memory_info().rss / 1024 / 1024,  # MB
        \"cpu_percent\": psutil.Process().cpu_percent()
    }
```

### Logging configuration

```python
import logging
import sys

def setup_logging(log_level: str = \"INFO\", log_file: str | None = None):
    \"\"\"Configure logging for production.\"\"\"
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

# Use in production server
if __name__ == \"__main__\":
    setup_logging(log_level=\"INFO\", log_file=\"/var/log/mcp-server.log\")
    mcp.run()
```

### Process monitoring

Monitor your server with tools like:

- **Supervisor** - Process management and auto-restart
- **PM2** - Node.js process manager (works with Python too)
- **systemd** - System service management
- **Docker health checks** - Container health monitoring

Example supervisor config:

```ini
[program:mcp-server]
command=/opt/mcp-server/.venv/bin/python server.py
directory=/opt/mcp-server
user=mcp
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/mcp-server.log
environment=PATH=/opt/mcp-server/.venv/bin
```

## Performance optimization

### Server configuration

```python
# Optimized production server
mcp = FastMCP(
    \"Production Server\",
    debug=False,                    # Disable debug mode
    log_level=\"INFO\",              # Reduce log verbosity
    stateless_http=True,            # Enable stateless mode for scaling
    host=\"0.0.0.0\",               # Accept connections from any host
    port=8000
)
```

### Resource management

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import aioredis
import asyncpg

@dataclass
class AppContext:
    db_pool: asyncpg.Pool
    redis: aioredis.Redis

@asynccontextmanager
async def optimized_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    \"\"\"Optimized lifespan with connection pooling.\"\"\"
    # Create connection pools
    db_pool = await asyncpg.create_pool(
        \"postgresql://user:pass@localhost/db\",
        min_size=5,
        max_size=20
    )
    
    redis = aioredis.from_url(
        \"redis://localhost:6379\",
        encoding=\"utf-8\",
        decode_responses=True
    )
    
    try:
        yield AppContext(db_pool=db_pool, redis=redis)
    finally:
        await db_pool.close()
        await redis.close()

mcp = FastMCP(\"Optimized Server\", lifespan=optimized_lifespan)
```

## Troubleshooting

### Common issues

**Server not starting:**
```bash
# Check if port is in use
lsof -i :8000

# Check server logs
uv run mcp dev server.py --log-level DEBUG
```

**Claude Desktop not connecting:**
```bash
# Verify installation
uv run mcp list

# Test server manually
uv run mcp dev server.py

# Check Claude Desktop logs (macOS)
tail -f ~/Library/Logs/Claude/mcp-server.log
```

**Performance issues:**
```bash
# Monitor resource usage
htop

# Check connection limits
ulimit -n

# Profile Python code
python -m cProfile server.py
```

### Debug tools

```python
@mcp.tool()
async def debug_server(ctx: Context) -> dict:
    \"\"\"Get comprehensive debug information.\"\"\"
    import platform
    import sys
    import os
    
    return {
        \"python\": {
            \"version\": sys.version,
            \"executable\": sys.executable,
            \"platform\": platform.platform()
        },
        \"environment\": {
            \"cwd\": os.getcwd(),
            \"env_vars\": dict(os.environ)
        },
        \"server\": {
            \"name\": ctx.fastmcp.name,
            \"settings\": ctx.fastmcp.settings.__dict__
        },
        \"request\": {
            \"id\": ctx.request_id,
            \"client_id\": ctx.client_id
        }
    }
```

## Best practices

### Development workflow

1. **Start with MCP Inspector** - Use `mcp dev` for rapid iteration
2. **Test with Claude Desktop** - Install and test real-world usage  
3. **Add environment configuration** - Use `.env` files for settings
4. **Implement health checks** - Add monitoring and debugging tools
5. **Plan deployment** - Choose appropriate transport and hosting

### Production readiness

- **Error handling** - Comprehensive error handling and recovery
- **Logging** - Structured logging with appropriate levels
- **Security** - Authentication, input validation, and rate limiting
- **Monitoring** - Health checks, metrics, and alerting
- **Scaling** - Connection pooling, stateless design, and load balancing

### Security considerations

- **Input validation** - Validate all tool and resource parameters
- **Environment variables** - Store secrets in environment, not code
- **Network security** - Use HTTPS in production, restrict access
- **Rate limiting** - Prevent abuse and resource exhaustion
- **Authentication** - Implement proper authentication for sensitive operations

## Next steps

- **[Streamable HTTP](streamable-http.md)** - Modern HTTP transport details
- **[ASGI integration](asgi-integration.md)** - Integrate with web frameworks
- **[Authentication](authentication.md)** - Secure your production servers
- **[Client development](writing-clients.md)** - Build clients to connect to your servers