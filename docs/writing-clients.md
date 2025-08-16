# Writing clients

Learn how to build MCP clients that can connect to servers using various transports and handle the full MCP protocol.

## Overview

MCP clients enable applications to:

- **Connect to MCP servers** using stdio, SSE, or Streamable HTTP transports
- **Discover capabilities** - List available tools, resources, and prompts
- **Execute operations** - Call tools, read resources, and get prompts
- **Handle real-time updates** - Receive notifications and progress updates

## Basic client setup

### stdio client

The simplest way to connect to MCP servers:

```python
"""
Basic stdio client example.
"""

import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def basic_stdio_client():
    """Connect to an MCP server via stdio."""
    
    # Configure server parameters
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "server", "quickstart", "stdio"],
        env={"UV_INDEX": os.environ.get("UV_INDEX", "")}
    )
    
    # Connect to server
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            init_result = await session.initialize()
            print(f"Connected to: {init_result.serverInfo.name}")
            print(f"Protocol version: {init_result.protocolVersion}")
            
            # List available tools
            tools = await session.list_tools()
            print(f"Available tools: {[tool.name for tool in tools.tools]}")
            
            # Call a tool
            if tools.tools:
                tool_name = tools.tools[0].name
                result = await session.call_tool(tool_name, {"a": 5, "b": 3})
                
                # Handle result
                if result.content:
                    content = result.content[0]
                    if hasattr(content, 'text'):
                        print(f"Tool result: {content.text}")

if __name__ == "__main__":
    asyncio.run(basic_stdio_client())
```

### HTTP client

Connect to servers using HTTP transports:

```python
"""
HTTP client using Streamable HTTP transport.
"""

import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def http_client_example():
    """Connect to MCP server via HTTP."""
    
    server_url = "http://localhost:8000/mcp"
    
    async with streamablehttp_client(server_url) as (read, write, session_info):
        async with ClientSession(read, write) as session:
            # Initialize connection
            await session.initialize()
            
            # Get server capabilities
            print(f"Server capabilities: {session.server_capabilities}")
            
            # List resources
            resources = await session.list_resources()
            print(f"Available resources: {[r.uri for r in resources.resources]}")
            
            # Read a resource
            if resources.resources:
                resource_uri = resources.resources[0].uri
                content = await session.read_resource(resource_uri)
                
                for item in content.contents:
                    if hasattr(item, 'text'):
                        print(f"Resource content: {item.text[:100]}...")

if __name__ == "__main__":
    asyncio.run(http_client_example())
```

## Advanced client patterns

### Error handling and retries

```python
"""
Robust client with error handling and retries.
"""

import asyncio
import logging
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError

logger = logging.getLogger(__name__)

class RobustMcpClient:
    """MCP client with robust error handling."""
    
    def __init__(self, server_params: StdioServerParameters, max_retries: int = 3):
        self.server_params = server_params
        self.max_retries = max_retries
        self.session: ClientSession | None = None
    
    async def connect(self) -> bool:
        """Connect to the server with retries."""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Connection attempt {attempt + 1}/{self.max_retries}")
                
                self.read_stream, self.write_stream = await stdio_client(
                    self.server_params
                ).__aenter__()
                
                self.session = ClientSession(self.read_stream, self.write_stream)
                await self.session.__aenter__()
                await self.session.initialize()
                
                logger.info("Successfully connected to MCP server")
                return True
                
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    logger.error("All connection attempts failed")
                    return False
                
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return False
    
    async def call_tool_safely(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call tool with error handling."""
        if not self.session:
            raise RuntimeError("Not connected to server")
        
        try:
            result = await self.session.call_tool(name, arguments)
            
            if result.isError:
                return {
                    "success": False,
                    "error": "Tool execution failed",
                    "content": [item.text if hasattr(item, 'text') else str(item) 
                               for item in result.content]
                }
            
            # Extract content
            content_items = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content_items.append(item.text)
                elif hasattr(item, 'data'):
                    content_items.append(f"<binary data: {len(item.data)} bytes>")
                else:
                    content_items.append(str(item))
            
            return {
                "success": True,
                "content": content_items,
                "structured": result.structuredContent if hasattr(result, 'structuredContent') else None
            }
            
        except McpError as e:
            logger.error(f"MCP error calling tool {name}: {e}")
            return {"success": False, "error": f"MCP error: {e}"}
        
        except Exception as e:
            logger.error(f"Unexpected error calling tool {name}: {e}")
            return {"success": False, "error": f"Unexpected error: {e}"}
    
    async def read_resource_safely(self, uri: str) -> dict[str, Any]:
        """Read resource with error handling."""
        if not self.session:
            raise RuntimeError("Not connected to server")
        
        try:
            result = await self.session.read_resource(uri)
            
            content_items = []
            for item in result.contents:
                if hasattr(item, 'text'):
                    content_items.append({"type": "text", "content": item.text})
                elif hasattr(item, 'data'):
                    content_items.append({
                        "type": "binary", 
                        "size": len(item.data),
                        "mime_type": getattr(item, 'mimeType', 'application/octet-stream')
                    })
                else:
                    content_items.append({"type": "unknown", "content": str(item)})
            
            return {"success": True, "contents": content_items}
            
        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            return {"success": False, "error": str(e)}
    
    async def disconnect(self):
        """Clean disconnect from server."""
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except:
                pass
            self.session = None

# Usage example
async def robust_client_example():
    """Example using the robust client."""
    server_params = StdioServerParameters(
        command="python", 
        args=["my_server.py"]
    )
    
    client = RobustMcpClient(server_params)
    
    if await client.connect():
        # Use the client
        result = await client.call_tool_safely("add", {"a": 10, "b": 20})
        print(f"Tool result: {result}")
        
        resource_result = await client.read_resource_safely("config://settings")
        print(f"Resource result: {resource_result}")
        
        await client.disconnect()
    else:
        print("Failed to connect to server")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(robust_client_example())
```

### Interactive client

```python
"""
Interactive MCP client with command-line interface.
"""

import asyncio
import cmd
import json
from typing import Any
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class InteractiveMcpClient(cmd.Cmd):
    """Interactive command-line MCP client."""
    
    intro = "Welcome to the MCP Interactive Client. Type help or ? for commands."
    prompt = "(mcp) "
    
    def __init__(self):
        super().__init__()
        self.session: ClientSession | None = None
        self.connected = False
        self.tools = []
        self.resources = []
        self.prompts = []
    
    def do_connect(self, args: str):
        """Connect to MCP server: connect <command> [args...]"""
        if not args:
            print("Usage: connect <command> [args...]")
            return
        
        parts = args.split()
        command = parts[0]
        server_args = parts[1:] if len(parts) > 1 else []
        
        asyncio.run(self._connect(command, server_args))
    
    async def _connect(self, command: str, args: list[str]):
        """Async connect implementation."""
        try:
            server_params = StdioServerParameters(command=command, args=args)
            
            self.read_stream, self.write_stream = await stdio_client(
                server_params
            ).__aenter__()
            
            self.session = ClientSession(self.read_stream, self.write_stream)
            await self.session.__aenter__()
            
            init_result = await self.session.initialize()
            
            print(f"Connected to: {init_result.serverInfo.name}")
            print(f"Version: {init_result.serverInfo.version}")
            
            self.connected = True
            await self._refresh_capabilities()
            
        except Exception as e:
            print(f"Connection failed: {e}")
    
    async def _refresh_capabilities(self):
        """Refresh server capabilities."""
        if not self.session:
            return
        
        try:
            # List tools
            tools_response = await self.session.list_tools()
            self.tools = tools_response.tools
            
            # List resources
            resources_response = await self.session.list_resources()
            self.resources = resources_response.resources
            
            # List prompts
            prompts_response = await self.session.list_prompts()
            self.prompts = prompts_response.prompts
            
            print(f"Discovered: {len(self.tools)} tools, {len(self.resources)} resources, {len(self.prompts)} prompts")
            
        except Exception as e:
            print(f"Error refreshing capabilities: {e}")
    
    def do_list(self, args: str):
        """List available tools, resources, or prompts: list [tools|resources|prompts]"""
        if not self.connected:
            print("Not connected to server")
            return
        
        if not args or args == "tools":
            print("Available tools:")
            for tool in self.tools:
                print(f"  {tool.name}: {tool.description}")
        
        elif args == "resources":
            print("Available resources:")
            for resource in self.resources:
                print(f"  {resource.uri}: {resource.name}")
        
        elif args == "prompts":
            print("Available prompts:")
            for prompt in self.prompts:
                print(f"  {prompt.name}: {prompt.description}")
        
        else:
            print("Usage: list [tools|resources|prompts]")
    
    def do_call(self, args: str):
        """Call a tool: call <tool_name> <json_arguments>"""
        if not self.connected:
            print("Not connected to server")
            return
        
        parts = args.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: call <tool_name> <json_arguments>")
            return
        
        tool_name, json_args = parts
        
        try:
            arguments = json.loads(json_args)
            asyncio.run(self._call_tool(tool_name, arguments))
        except json.JSONDecodeError:
            print("Invalid JSON arguments")
    
    async def _call_tool(self, name: str, arguments: dict[str, Any]):
        """Async tool call implementation."""
        try:
            result = await self.session.call_tool(name, arguments)
            
            if result.isError:
                print("Tool execution failed:")
                for content in result.content:
                    if hasattr(content, 'text'):
                        print(f"  {content.text}")
            else:
                print("Tool result:")
                for content in result.content:
                    if hasattr(content, 'text'):
                        print(f"  {content.text}")
                
                # Show structured content if available
                if hasattr(result, 'structuredContent') and result.structuredContent:
                    print("Structured result:")
                    print(f"  {json.dumps(result.structuredContent, indent=2)}")
        
        except Exception as e:
            print(f"Error calling tool: {e}")
    
    def do_read(self, args: str):
        """Read a resource: read <resource_uri>"""
        if not self.connected:
            print("Not connected to server")
            return
        
        if not args:
            print("Usage: read <resource_uri>")
            return
        
        asyncio.run(self._read_resource(args))
    
    async def _read_resource(self, uri: str):
        """Async resource read implementation."""
        try:
            result = await self.session.read_resource(uri)
            
            print(f"Resource content for {uri}:")
            for content in result.contents:
                if hasattr(content, 'text'):
                    print(content.text)
                elif hasattr(content, 'data'):
                    print(f"<binary data: {len(content.data)} bytes>")
        
        except Exception as e:
            print(f"Error reading resource: {e}")
    
    def do_prompt(self, args: str):
        """Get a prompt: prompt <prompt_name> <json_arguments>"""
        if not self.connected:
            print("Not connected to server")
            return
        
        parts = args.split(maxsplit=1)
        if len(parts) < 1:
            print("Usage: prompt <prompt_name> [json_arguments]")
            return
        
        prompt_name = parts[0]
        arguments = {}
        
        if len(parts) == 2:
            try:
                arguments = json.loads(parts[1])
            except json.JSONDecodeError:
                print("Invalid JSON arguments")
                return
        
        asyncio.run(self._get_prompt(prompt_name, arguments))
    
    async def _get_prompt(self, name: str, arguments: dict[str, Any]):
        """Async prompt get implementation."""
        try:
            result = await self.session.get_prompt(name, arguments)
            
            print(f"Prompt: {result.description}")
            for message in result.messages:
                print(f"  {message.role}: {message.content.text}")
        
        except Exception as e:
            print(f"Error getting prompt: {e}")
    
    def do_disconnect(self, args: str):
        """Disconnect from server"""
        if self.connected:
            asyncio.run(self._disconnect())
            print("Disconnected")
        else:
            print("Not connected")
    
    async def _disconnect(self):
        """Async disconnect implementation."""
        if self.session:
            await self.session.__aexit__(None, None, None)
            self.session = None
        self.connected = False
    
    def do_quit(self, args: str):
        """Quit the client"""
        if self.connected:
            asyncio.run(self._disconnect())
        return True
    
    def do_EOF(self, args: str):
        """Handle Ctrl+D"""
        print()
        return self.do_quit(args)

# Run the interactive client
if __name__ == "__main__":
    InteractiveMcpClient().cmdloop()
```

## Client-side caching

### Smart caching client

```python
"""
MCP client with intelligent caching.
"""

import asyncio
import hashlib
import time
from typing import Any, Dict, Optional
from dataclasses import dataclass
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

@dataclass
class CacheEntry:
    """Cache entry with TTL support."""
    data: Any
    timestamp: float
    ttl: float

class CachingMcpClient:
    """MCP client with caching capabilities."""
    
    def __init__(self, server_params: StdioServerParameters, default_ttl: float = 300):
        self.server_params = server_params
        self.default_ttl = default_ttl
        self.cache: Dict[str, CacheEntry] = {}
        self.session: Optional[ClientSession] = None
    
    def _cache_key(self, operation: str, **kwargs) -> str:
        """Generate cache key from operation and parameters."""
        key_data = f"{operation}:{kwargs}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _is_cache_valid(self, entry: CacheEntry) -> bool:
        """Check if cache entry is still valid."""
        return time.time() - entry.timestamp < entry.ttl
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get cached value if valid."""
        if key in self.cache:
            entry = self.cache[key]
            if self._is_cache_valid(entry):
                return entry.data
            else:
                del self.cache[key]
        return None
    
    def _set_cached(self, key: str, data: Any, ttl: Optional[float] = None):
        """Cache data with TTL."""
        if ttl is None:
            ttl = self.default_ttl
        
        self.cache[key] = CacheEntry(
            data=data,
            timestamp=time.time(),
            ttl=ttl
        )
    
    async def connect(self):
        """Connect to the MCP server."""
        self.read_stream, self.write_stream = await stdio_client(
            self.server_params
        ).__aenter__()
        
        self.session = ClientSession(self.read_stream, self.write_stream)
        await self.session.__aenter__()
        await self.session.initialize()
    
    async def list_tools_cached(self, ttl: float = 600) -> list:
        """List tools with caching (tools change infrequently)."""
        cache_key = self._cache_key("list_tools")
        cached = self._get_cached(cache_key)
        
        if cached is not None:
            return cached
        
        if not self.session:
            raise RuntimeError("Not connected")
        
        result = await self.session.list_tools()
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in result.tools
        ]
        
        self._set_cached(cache_key, tools, ttl)
        return tools
    
    async def call_tool_cached(
        self, 
        name: str, 
        arguments: Dict[str, Any],
        ttl: Optional[float] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Call tool with optional caching."""
        cache_key = self._cache_key("call_tool", name=name, arguments=arguments)
        
        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return {"cached": True, **cached}
        
        if not self.session:
            raise RuntimeError("Not connected")
        
        result = await self.session.call_tool(name, arguments)
        
        # Process result
        processed_result = {
            "success": not result.isError,
            "content": [
                item.text if hasattr(item, 'text') else str(item)
                for item in result.content
            ]
        }
        
        if hasattr(result, 'structuredContent') and result.structuredContent:
            processed_result["structured"] = result.structuredContent
        
        # Cache successful results if TTL specified
        if ttl is not None and processed_result["success"]:
            self._set_cached(cache_key, processed_result, ttl)
        
        return {"cached": False, **processed_result}
    
    async def read_resource_cached(
        self,
        uri: str,
        ttl: float = 60,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Read resource with caching."""
        cache_key = self._cache_key("read_resource", uri=uri)
        
        if not force_refresh:
            cached = self._get_cached(cache_key)
            if cached is not None:
                return {"cached": True, **cached}
        
        if not self.session:
            raise RuntimeError("Not connected")
        
        result = await self.session.read_resource(uri)
        
        processed_result = {
            "uri": uri,
            "contents": [
                {
                    "type": "text" if hasattr(item, 'text') else "binary",
                    "content": item.text if hasattr(item, 'text') else f"<{len(item.data)} bytes>"
                }
                for item in result.contents
            ]
        }
        
        self._set_cached(cache_key, processed_result, ttl)
        return {"cached": False, **processed_result}
    
    def clear_cache(self, pattern: Optional[str] = None):
        """Clear cache entries matching pattern."""
        if pattern is None:
            self.cache.clear()
        else:
            keys_to_remove = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.cache[key]
    
    def cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        valid_entries = sum(
            1 for entry in self.cache.values()
            if now - entry.timestamp < entry.ttl
        )
        
        return {
            "total_entries": len(self.cache),
            "valid_entries": valid_entries,
            "expired_entries": len(self.cache) - valid_entries,
            "cache_hit_potential": valid_entries / len(self.cache) if self.cache else 0
        }

# Usage example
async def caching_client_example():
    """Example using caching client."""
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"]
    )
    
    client = CachingMcpClient(server_params, default_ttl=120)
    await client.connect()
    
    # First call - will hit server
    result1 = await client.call_tool_cached("add", {"a": 5, "b": 3}, ttl=60)
    print(f"First call (cached: {result1['cached']}): {result1['content']}")
    
    # Second call - will use cache
    result2 = await client.call_tool_cached("add", {"a": 5, "b": 3})
    print(f"Second call (cached: {result2['cached']}): {result2['content']}")
    
    # Resource with caching
    resource1 = await client.read_resource_cached("config://settings", ttl=30)
    print(f"Resource (cached: {resource1['cached']})")
    
    # Cache stats
    stats = client.cache_stats()
    print(f"Cache stats: {stats}")

if __name__ == "__main__":
    asyncio.run(caching_client_example())
```

## Production client patterns

### Connection pooling client

```python
"""
Production MCP client with connection pooling.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

class ConnectionPool:
    """Connection pool for MCP clients."""
    
    def __init__(
        self,
        server_params: StdioServerParameters,
        pool_size: int = 5,
        max_retries: int = 3
    ):
        self.server_params = server_params
        self.pool_size = pool_size
        self.max_retries = max_retries
        self.available_connections: asyncio.Queue = asyncio.Queue()
        self.active_connections: set = set()
        self.closed = False
    
    async def initialize(self):
        """Initialize the connection pool."""
        for _ in range(self.pool_size):
            connection = await self._create_connection()
            if connection:
                await self.available_connections.put(connection)
    
    async def _create_connection(self) -> Optional[ClientSession]:
        """Create a new connection with retries."""
        for attempt in range(self.max_retries):
            try:
                read_stream, write_stream = await stdio_client(
                    self.server_params
                ).__aenter__()
                
                session = ClientSession(read_stream, write_stream)
                await session.__aenter__()
                await session.initialize()
                
                logger.info("Created new MCP connection")
                return session
                
            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        logger.error("Failed to create connection after all retries")
        return None
    
    @asynccontextmanager
    async def get_connection(self):
        """Get a connection from the pool."""
        if self.closed:
            raise RuntimeError("Connection pool is closed")
        
        try:
            # Try to get an available connection
            connection = await asyncio.wait_for(
                self.available_connections.get(),
                timeout=10.0
            )
            
            self.active_connections.add(connection)
            yield connection
            
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for available connection")
            raise
        
        finally:
            # Return connection to pool
            if connection in self.active_connections:
                self.active_connections.remove(connection)
                await self.available_connections.put(connection)
    
    async def close(self):
        """Close all connections in the pool."""
        self.closed = True
        
        # Close active connections
        for connection in list(self.active_connections):
            try:
                await connection.__aexit__(None, None, None)
            except:
                pass
        
        # Close available connections
        while not self.available_connections.empty():
            try:
                connection = self.available_connections.get_nowait()
                await connection.__aexit__(None, None, None)
            except:
                pass
        
        logger.info("Connection pool closed")

class PooledMcpClient:
    """MCP client using connection pooling."""
    
    def __init__(self, connection_pool: ConnectionPool):
        self.pool = connection_pool
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call tool using pooled connection."""
        async with self.pool.get_connection() as session:
            result = await session.call_tool(name, arguments)
            
            return {
                "success": not result.isError,
                "content": [
                    item.text if hasattr(item, 'text') else str(item)
                    for item in result.content
                ],
                "structured": getattr(result, 'structuredContent', None)
            }
    
    async def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read resource using pooled connection."""
        async with self.pool.get_connection() as session:
            result = await session.read_resource(uri)
            
            return {
                "uri": uri,
                "contents": [
                    item.text if hasattr(item, 'text') else f"<binary: {len(item.data)} bytes>"
                    for item in result.contents
                ]
            }
    
    async def list_capabilities(self) -> Dict[str, List[str]]:
        """List server capabilities using pooled connection."""
        async with self.pool.get_connection() as session:
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()
            
            return {
                "tools": [tool.name for tool in tools.tools],
                "resources": [resource.uri for resource in resources.resources],
                "prompts": [prompt.name for prompt in prompts.prompts]
            }

# Usage example
async def pooled_client_example():
    """Example using connection pool."""
    server_params = StdioServerParameters(
        command="python",
        args=["server.py"]
    )
    
    # Create and initialize connection pool
    pool = ConnectionPool(server_params, pool_size=3)
    await pool.initialize()
    
    client = PooledMcpClient(pool)
    
    try:
        # Concurrent operations using pool
        tasks = [
            client.call_tool("add", {"a": i, "b": i*2})
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        
        for i, result in enumerate(results):
            print(f"Task {i}: {result}")
        
        # List capabilities
        capabilities = await client.list_capabilities()
        print(f"Server capabilities: {capabilities}")
        
    finally:
        await pool.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(pooled_client_example())
```

## Testing client implementations

### Client testing framework

```python
"""
Testing framework for MCP clients.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from mcp import ClientSession
from mcp.types import Tool, InitializeResult, ServerInfo, ListToolsResult

class MockMcpSession:
    """Mock MCP session for testing."""
    
    def __init__(self):
        self.tools = [
            Tool(name="add", description="Add numbers", inputSchema={}),
            Tool(name="multiply", description="Multiply numbers", inputSchema={})
        ]
        self.initialized = False
    
    async def initialize(self):
        self.initialized = True
        return InitializeResult(
            protocolVersion="2025-06-18",
            serverInfo=ServerInfo(name="Test Server", version="1.0.0"),
            capabilities={}
        )
    
    async def list_tools(self):
        if not self.initialized:
            raise RuntimeError("Not initialized")
        return ListToolsResult(tools=self.tools)
    
    async def call_tool(self, name: str, arguments: dict):
        if not self.initialized:
            raise RuntimeError("Not initialized")
        
        if name == "add":
            result = arguments["a"] + arguments["b"]
        elif name == "multiply":
            result = arguments["a"] * arguments["b"]
        else:
            raise ValueError(f"Unknown tool: {name}")
        
        mock_result = Mock()
        mock_result.isError = False
        mock_result.content = [Mock(text=str(result))]
        mock_result.structuredContent = {"result": result}
        
        return mock_result

@pytest.fixture
async def mock_session():
    """Pytest fixture providing mock session."""
    return MockMcpSession()

@pytest.mark.asyncio
async def test_client_initialization(mock_session):
    """Test client initialization."""
    result = await mock_session.initialize()
    assert result.serverInfo.name == "Test Server"
    assert mock_session.initialized

@pytest.mark.asyncio
async def test_tool_listing(mock_session):
    """Test tool listing."""
    await mock_session.initialize()
    tools = await mock_session.list_tools()
    
    assert len(tools.tools) == 2
    assert tools.tools[0].name == "add"
    assert tools.tools[1].name == "multiply"

@pytest.mark.asyncio
async def test_tool_calling(mock_session):
    """Test tool calling."""
    await mock_session.initialize()
    
    # Test add tool
    result = await mock_session.call_tool("add", {"a": 5, "b": 3})
    assert not result.isError
    assert result.content[0].text == "8"
    
    # Test multiply tool
    result = await mock_session.call_tool("multiply", {"a": 4, "b": 6})
    assert not result.isError
    assert result.content[0].text == "24"

@pytest.mark.asyncio
async def test_error_handling(mock_session):
    """Test error handling."""
    await mock_session.initialize()
    
    with pytest.raises(ValueError):
        await mock_session.call_tool("unknown_tool", {})

# Integration test with real client
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_client_integration():
    """Integration test with real MCP server."""
    # This would connect to a real server for integration testing
    # server_params = StdioServerParameters(command="python", args=["test_server.py"])
    # 
    # async with stdio_client(server_params) as (read, write):
    #     async with ClientSession(read, write) as session:
    #         await session.initialize()
    #         tools = await session.list_tools()
    #         assert len(tools.tools) > 0
    pass
```

## Best practices

### Client design guidelines

- **Connection management** - Use connection pooling for high-throughput applications
- **Error handling** - Implement comprehensive error handling and retries
- **Caching** - Cache stable data like tool lists and resource schemas
- **Monitoring** - Track connection health and operation latency
- **Resource cleanup** - Always clean up connections and resources

### Performance optimization

- **Async operations** - Use async/await throughout for better concurrency
- **Connection reuse** - Pool connections for multiple operations
- **Batch operations** - Group related operations when possible
- **Smart caching** - Cache responses based on data volatility
- **Timeout management** - Set appropriate timeouts for operations

### Security considerations

- **Input validation** - Validate all data before sending to servers
- **Credential management** - Secure handling of authentication tokens
- **Transport security** - Use secure transports (HTTPS, authenticated connections)
- **Error information** - Don't expose sensitive data in error messages
- **Audit logging** - Log all operations for security monitoring

## Next steps

- **[OAuth for clients](oauth-clients.md)** - Implement client-side authentication
- **[Display utilities](display-utilities.md)** - UI helpers for client applications
- **[Parsing results](parsing-results.md)** - Handle complex tool responses
- **[Authentication](authentication.md)** - Understanding server-side authentication