# Low-level server

Learn how to build MCP servers using the low-level protocol implementation for maximum control and customization.

## Overview

Low-level server development provides:

- **Protocol control** - Direct access to MCP protocol messages
- **Custom transports** - Implement custom transport mechanisms
- **Advanced error handling** - Fine-grained error control and reporting
- **Performance optimization** - Optimize for specific use cases
- **Protocol extensions** - Add custom protocol features

## Basic low-level server

### Core server implementation

```python
"""
Low-level MCP server implementation.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from mcp.types import (
    JSONRPCMessage, JSONRPCRequest, JSONRPCResponse, JSONRPCError,
    InitializeRequest, InitializeResult, ServerInfo,
    ListToolsRequest, ListToolsResult, Tool,
    CallToolRequest, CallToolResult, TextContent,
    ListResourcesRequest, ListResourcesResult, Resource,
    ReadResourceRequest, ReadResourceResult,
    ListPromptsRequest, ListPromptsResult, Prompt,
    GetPromptRequest, GetPromptResult, PromptMessage
)
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.session import ServerSession

logger = logging.getLogger(__name__)

class LowLevelServer:
    """Low-level MCP server with direct protocol access."""
    
    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        
        # Protocol handlers
        self.request_handlers: Dict[str, Callable] = {}
        self.notification_handlers: Dict[str, Callable] = {}
        
        # Server state
        self.initialized = False
        self.capabilities = {}
        self.client_capabilities = {}
        
        # Register core handlers
        self._register_core_handlers()
        
        # Custom tool, resource, and prompt registries
        self.tools: Dict[str, Callable] = {}
        self.resources: Dict[str, Callable] = {}
        self.prompts: Dict[str, Callable] = {}
    
    def _register_core_handlers(self):
        """Register core MCP protocol handlers."""
        self.request_handlers.update({
            "initialize": self._handle_initialize,
            "tools/list": self._handle_list_tools,
            "tools/call": self._handle_call_tool,
            "resources/list": self._handle_list_resources,
            "resources/read": self._handle_read_resource,
            "prompts/list": self._handle_list_prompts,
            "prompts/get": self._handle_get_prompt,
        })
        
        self.notification_handlers.update({
            "initialized": self._handle_initialized,
            "progress": self._handle_progress,
        })
    
    def register_tool(self, name: str, handler: Callable, description: str = "", input_schema: Dict[str, Any] = None):
        """Register a tool handler."""
        self.tools[name] = {
            'handler': handler,
            'description': description,
            'input_schema': input_schema or {}
        }
    
    def register_resource(self, uri: str, handler: Callable, name: str = "", description: str = ""):
        """Register a resource handler."""
        self.resources[uri] = {
            'handler': handler,
            'name': name or uri,
            'description': description
        }
    
    def register_prompt(self, name: str, handler: Callable, description: str = "", arguments: List[Dict[str, Any]] = None):
        """Register a prompt handler."""
        self.prompts[name] = {
            'handler': handler,
            'description': description,
            'arguments': arguments or []
        }
    
    async def process_message(self, message: JSONRPCMessage) -> Optional[JSONRPCMessage]:
        """Process an incoming JSON-RPC message."""
        try:
            if isinstance(message, JSONRPCRequest):
                return await self._handle_request(message)
            elif hasattr(message, 'method'):  # Notification
                await self._handle_notification(message)
                return None
            else:
                logger.warning(f"Unknown message type: {type(message)}")
                return None
                
        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            if isinstance(message, JSONRPCRequest):
                return JSONRPCResponse(
                    id=message.id,
                    error=JSONRPCError(
                        code=-32603,  # Internal error
                        message=f"Internal server error: {str(e)}"
                    )
                )
            return None
    
    async def _handle_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Handle a JSON-RPC request."""
        method = request.method
        params = request.params or {}
        
        if method not in self.request_handlers:
            return JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(
                    code=-32601,  # Method not found
                    message=f"Method not found: {method}"
                )
            )
        
        try:
            handler = self.request_handlers[method]
            
            # Call handler with proper parameters
            if asyncio.iscoroutinefunction(handler):
                result = await handler(params)
            else:
                result = handler(params)
            
            return JSONRPCResponse(id=request.id, result=result)
            
        except Exception as e:
            logger.exception(f"Error handling request {method}: {e}")
            return JSONRPCResponse(
                id=request.id,
                error=JSONRPCError(
                    code=-32603,  # Internal error
                    message=str(e)
                )
            )
    
    async def _handle_notification(self, notification):
        """Handle a JSON-RPC notification."""
        method = getattr(notification, 'method', None)
        params = getattr(notification, 'params', {}) or {}
        
        if method in self.notification_handlers:
            try:
                handler = self.notification_handlers[method]
                if asyncio.iscoroutinefunction(handler):
                    await handler(params)
                else:
                    handler(params)
            except Exception as e:
                logger.exception(f"Error handling notification {method}: {e}")
        else:
            logger.warning(f"Unknown notification method: {method}")
    
    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request."""
        protocol_version = params.get('protocolVersion')
        client_info = params.get('clientInfo', {})
        self.client_capabilities = params.get('capabilities', {})
        
        logger.info(f"Initializing server for client: {client_info.get('name', 'Unknown')}")
        
        # Define server capabilities
        self.capabilities = {
            "tools": {"listChanged": True} if self.tools else None,
            "resources": {"subscribe": True, "listChanged": True} if self.resources else None,
            "prompts": {"listChanged": True} if self.prompts else None,
            "logging": {},
        }
        
        # Remove None capabilities
        self.capabilities = {k: v for k, v in self.capabilities.items() if v is not None}
        
        return {
            "protocolVersion": protocol_version,
            "capabilities": self.capabilities,
            "serverInfo": {
                "name": self.name,
                "version": self.version
            }
        }
    
    def _handle_initialized(self, params: Dict[str, Any]):
        """Handle initialized notification."""
        self.initialized = True
        logger.info("Server initialization completed")
    
    async def _handle_list_tools(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        tools = []
        for name, tool_info in self.tools.items():
            tools.append({
                "name": name,
                "description": tool_info['description'],
                "inputSchema": tool_info['input_schema']
            })
        
        return {"tools": tools}
    
    async def _handle_call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        name = params.get('name')
        arguments = params.get('arguments', {})
        
        if name not in self.tools:
            raise ValueError(f"Tool not found: {name}")
        
        tool_info = self.tools[name]
        handler = tool_info['handler']
        
        try:
            # Call the tool handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)
            
            # Convert result to content format
            if isinstance(result, str):
                content = [{"type": "text", "text": result}]
            elif isinstance(result, dict):
                content = [{"type": "text", "text": json.dumps(result, indent=2)}]
            elif isinstance(result, list):
                content = [{"type": "text", "text": json.dumps(result, indent=2)}]
            else:
                content = [{"type": "text", "text": str(result)}]
            
            return {
                "content": content,
                "isError": False
            }
            
        except Exception as e:
            logger.exception(f"Error executing tool {name}: {e}")
            return {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True
            }
    
    async def _handle_list_resources(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/list request."""
        resources = []
        for uri, resource_info in self.resources.items():
            resources.append({
                "uri": uri,
                "name": resource_info['name'],
                "description": resource_info['description'],
                "mimeType": "text/plain"  # Default, can be customized
            })
        
        return {"resources": resources}
    
    async def _handle_read_resource(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get('uri')
        
        if uri not in self.resources:
            raise ValueError(f"Resource not found: {uri}")
        
        resource_info = self.resources[uri]
        handler = resource_info['handler']
        
        try:
            # Call the resource handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(uri)
            else:
                result = handler(uri)
            
            # Convert result to content format
            if isinstance(result, str):
                contents = [{"type": "text", "text": result}]
            elif isinstance(result, bytes):
                contents = [{"type": "blob", "blob": result}]
            else:
                contents = [{"type": "text", "text": str(result)}]
            
            return {"contents": contents}
            
        except Exception as e:
            logger.exception(f"Error reading resource {uri}: {e}")
            raise
    
    async def _handle_list_prompts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle prompts/list request."""
        prompts = []
        for name, prompt_info in self.prompts.items():
            prompts.append({
                "name": name,
                "description": prompt_info['description'],
                "arguments": prompt_info['arguments']
            })
        
        return {"prompts": prompts}
    
    async def _handle_get_prompt(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle prompts/get request."""
        name = params.get('name')
        arguments = params.get('arguments', {})
        
        if name not in self.prompts:
            raise ValueError(f"Prompt not found: {name}")
        
        prompt_info = self.prompts[name]
        handler = prompt_info['handler']
        
        try:
            # Call the prompt handler
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)
            
            # Convert result to messages format
            if isinstance(result, str):
                messages = [{"role": "user", "content": {"type": "text", "text": result}}]
            elif isinstance(result, list):
                messages = result
            elif isinstance(result, dict):
                if 'messages' in result:
                    messages = result['messages']
                else:
                    messages = [{"role": "user", "content": {"type": "text", "text": json.dumps(result)}}]
            else:
                messages = [{"role": "user", "content": {"type": "text", "text": str(result)}}]
            
            return {
                "description": prompt_info['description'],
                "messages": messages
            }
            
        except Exception as e:
            logger.exception(f"Error getting prompt {name}: {e}")
            raise
    
    def _handle_progress(self, params: Dict[str, Any]):
        """Handle progress notification."""
        progress_token = params.get('progressToken')
        progress = params.get('progress')
        total = params.get('total')
        
        logger.info(f"Progress update: {progress}/{total} (token: {progress_token})")
    
    async def run_stdio(self):
        """Run server with stdio transport."""
        server = Server()
        
        @server.list_tools()
        async def list_tools() -> List[Tool]:
            tools = []
            for name, tool_info in self.tools.items():
                tools.append(Tool(
                    name=name,
                    description=tool_info['description'],
                    inputSchema=tool_info['input_schema']
                ))
            return tools
        
        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> List[TextContent]:
            if name not in self.tools:
                raise ValueError(f"Tool not found: {name}")
            
            tool_info = self.tools[name]
            handler = tool_info['handler']
            
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)
            
            return [TextContent(type="text", text=str(result))]
        
        # Add resource and prompt handlers similarly...
        
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializeResult(
                    protocolVersion="2025-06-18",
                    capabilities=server.get_capabilities(),
                    serverInfo=ServerInfo(name=self.name, version=self.version)
                )
            )

# Usage example
def create_calculator_server():
    """Create a low-level calculator server."""
    server = LowLevelServer("Calculator Server", "1.0.0")
    
    # Register calculator tools
    def add(a: float, b: float) -> float:
        """Add two numbers."""
        return a + b
    
    def multiply(a: float, b: float) -> float:
        """Multiply two numbers."""
        return a * b
    
    def divide(a: float, b: float) -> float:
        """Divide two numbers."""
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
    
    # Register tools with schemas
    server.register_tool(
        "add",
        add,
        "Add two numbers together",
        {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    )
    
    server.register_tool(
        "multiply",
        multiply,
        "Multiply two numbers",
        {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
    )
    
    server.register_tool(
        "divide",
        divide,
        "Divide first number by second number",
        {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "Dividend"},
                "b": {"type": "number", "description": "Divisor"}
            },
            "required": ["a", "b"]
        }
    )
    
    # Register a configuration resource
    def get_config(uri: str) -> str:
        """Get server configuration."""
        if uri == "config://settings":
            return json.dumps({
                "precision": 6,
                "max_operations": 1000,
                "supported_operations": ["add", "multiply", "divide"]
            }, indent=2)
        return "Configuration not found"
    
    server.register_resource(
        "config://settings",
        get_config,
        "Server Settings",
        "Calculator server configuration"
    )
    
    # Register a calculation prompt
    def math_prompt(operation: str = "add", **kwargs) -> str:
        """Generate a math problem prompt."""
        if operation == "add":
            return f"Please add the following numbers: {kwargs.get('numbers', [1, 2, 3])}"
        elif operation == "multiply":
            return f"Please multiply these numbers: {kwargs.get('numbers', [2, 3, 4])}"
        else:
            return f"Please perform {operation} on the given numbers"
    
    server.register_prompt(
        "math_problem",
        math_prompt,
        "Generate a math problem",
        [
            {"name": "operation", "description": "Type of operation", "required": False},
            {"name": "numbers", "description": "Numbers to use", "required": False}
        ]
    )
    
    return server

if __name__ == "__main__":
    # Create and run the server
    calc_server = create_calculator_server()
    asyncio.run(calc_server.run_stdio())
```

## Custom transport implementation

### HTTP transport

```python
"""
Custom HTTP transport for low-level MCP server.
"""

import asyncio
import json
from aiohttp import web, WSMsgType
from typing import Dict, Any, Optional

class HttpTransport:
    """HTTP transport for MCP server."""
    
    def __init__(self, server: LowLevelServer, host: str = "localhost", port: int = 8000):
        self.server = server
        self.host = host
        self.port = port
        self.app = web.Application()
        self.sessions: Dict[str, Any] = {}
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup HTTP routes."""
        self.app.router.add_post('/mcp', self._handle_http_request)
        self.app.router.add_get('/mcp/ws', self._handle_websocket)
        self.app.router.add_get('/health', self._health_check)
        self.app.router.add_get('/', self._index)
    
    async def _handle_http_request(self, request):
        """Handle HTTP POST request."""
        try:
            data = await request.json()
            
            # Convert to JSONRPCRequest
            message = self._parse_jsonrpc_message(data)
            if not message:
                return web.json_response(
                    {"error": "Invalid JSON-RPC message"},
                    status=400
                )
            
            # Process message
            response = await self.server.process_message(message)
            
            if response:
                return web.json_response(self._serialize_response(response))
            else:
                return web.Response(status=204)  # No content for notifications
                
        except json.JSONDecodeError:
            return web.json_response(
                {"error": "Invalid JSON"},
                status=400
            )
        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500
            )
    
    async def _handle_websocket(self, request):
        """Handle WebSocket connection."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        session_id = id(ws)
        self.sessions[session_id] = ws
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        message = self._parse_jsonrpc_message(data)
                        
                        if message:
                            response = await self.server.process_message(message)
                            if response:
                                await ws.send_str(json.dumps(self._serialize_response(response)))
                    
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "error": {"code": -32603, "message": str(e)},
                            "id": None
                        }
                        await ws.send_str(json.dumps(error_response))
                
                elif msg.type == WSMsgType.ERROR:
                    print(f'WebSocket error: {ws.exception()}')
                    break
        
        finally:
            if session_id in self.sessions:
                del self.sessions[session_id]
        
        return ws
    
    async def _health_check(self, request):
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "server": self.server.name,
            "version": self.server.version,
            "initialized": self.server.initialized
        })
    
    async def _index(self, request):
        """Index page with server info."""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{self.server.name}</title>
        </head>
        <body>
            <h1>{self.server.name}</h1>
            <p>Version: {self.server.version}</p>
            <p>Status: {"Initialized" if self.server.initialized else "Not initialized"}</p>
            <h2>Endpoints:</h2>
            <ul>
                <li>POST /mcp - JSON-RPC over HTTP</li>
                <li>GET /mcp/ws - WebSocket connection</li>
                <li>GET /health - Health check</li>
            </ul>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')
    
    def _parse_jsonrpc_message(self, data: Dict[str, Any]):
        """Parse JSON-RPC message from data."""
        if not isinstance(data, dict) or data.get('jsonrpc') != '2.0':
            return None
        
        if 'method' in data:
            # Request or notification
            return type('JSONRPCMessage', (), {
                'jsonrpc': data['jsonrpc'],
                'method': data['method'],
                'params': data.get('params'),
                'id': data.get('id')
            })()
        
        return None
    
    def _serialize_response(self, response) -> Dict[str, Any]:
        """Serialize response to JSON-RPC format."""
        result = {
            "jsonrpc": "2.0",
            "id": getattr(response, 'id', None)
        }
        
        if hasattr(response, 'result'):
            result["result"] = response.result
        elif hasattr(response, 'error'):
            result["error"] = {
                "code": response.error.code,
                "message": response.error.message,
                "data": getattr(response.error, 'data', None)
            }
        
        return result
    
    async def run(self):
        """Run the HTTP server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        
        print(f"MCP server running on http://{self.host}:{self.port}")
        
        try:
            await asyncio.Future()  # Run forever
        except KeyboardInterrupt:
            pass
        finally:
            await runner.cleanup()

# Usage example
async def run_http_server():
    """Run calculator server with HTTP transport."""
    server = create_calculator_server()
    transport = HttpTransport(server, "localhost", 8000)
    await transport.run()

if __name__ == "__main__":
    asyncio.run(run_http_server())
```

## Advanced features

### Custom protocol extensions

```python
"""
Custom protocol extensions for MCP server.
"""

from typing import Any, Dict, List, Optional
import time
import uuid

class ExtendedServer(LowLevelServer):
    """MCP server with custom protocol extensions."""
    
    def __init__(self, name: str, version: str = "1.0.0"):
        super().__init__(name, version)
        
        # Extension state
        self.metrics = {}
        self.sessions = {}
        
        # Register extension handlers
        self._register_extensions()
    
    def _register_extensions(self):
        """Register custom protocol extensions."""
        # Custom methods
        self.request_handlers.update({
            "server/metrics": self._handle_get_metrics,
            "server/status": self._handle_get_status,
            "tools/batch": self._handle_batch_tools,
            "session/create": self._handle_create_session,
            "session/destroy": self._handle_destroy_session,
        })
        
        # Custom notifications
        self.notification_handlers.update({
            "client/heartbeat": self._handle_heartbeat,
            "metrics/report": self._handle_metrics_report,
        })
    
    async def process_message(self, message):
        """Enhanced message processing with metrics."""
        start_time = time.time()
        method = getattr(message, 'method', 'unknown')
        
        try:
            result = await super().process_message(message)
            
            # Record success metrics
            self._record_metric(method, time.time() - start_time, True)
            
            return result
            
        except Exception as e:
            # Record error metrics
            self._record_metric(method, time.time() - start_time, False)
            raise
    
    def _record_metric(self, method: str, duration: float, success: bool):
        """Record operation metrics."""
        if method not in self.metrics:
            self.metrics[method] = {
                'count': 0,
                'success_count': 0,
                'error_count': 0,
                'total_duration': 0.0,
                'avg_duration': 0.0,
                'last_called': None
            }
        
        metric = self.metrics[method]
        metric['count'] += 1
        metric['total_duration'] += duration
        metric['avg_duration'] = metric['total_duration'] / metric['count']
        metric['last_called'] = time.time()
        
        if success:
            metric['success_count'] += 1
        else:
            metric['error_count'] += 1
    
    async def _handle_get_metrics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle server/metrics request."""
        return {
            "metrics": self.metrics,
            "server_uptime": time.time() - getattr(self, '_start_time', time.time()),
            "active_sessions": len(self.sessions)
        }
    
    async def _handle_get_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle server/status request."""
        return {
            "name": self.name,
            "version": self.version,
            "initialized": self.initialized,
            "capabilities": self.capabilities,
            "tools_count": len(self.tools),
            "resources_count": len(self.resources),
            "prompts_count": len(self.prompts),
            "uptime": time.time() - getattr(self, '_start_time', time.time())
        }
    
    async def _handle_batch_tools(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/batch request for executing multiple tools."""
        calls = params.get('calls', [])
        results = []
        
        for call in calls:
            tool_name = call.get('name')
            arguments = call.get('arguments', {})
            call_id = call.get('id', str(uuid.uuid4()))
            
            try:
                # Use existing tool call logic
                tool_result = await self._handle_call_tool({
                    'name': tool_name,
                    'arguments': arguments
                })
                
                results.append({
                    'id': call_id,
                    'result': tool_result,
                    'success': True
                })
                
            except Exception as e:
                results.append({
                    'id': call_id,
                    'error': str(e),
                    'success': False
                })
        
        return {"results": results}
    
    async def _handle_create_session(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle session/create request."""
        session_id = str(uuid.uuid4())
        session_name = params.get('name', f"Session {session_id[:8]}")
        
        self.sessions[session_id] = {
            'id': session_id,
            'name': session_name,
            'created_at': time.time(),
            'last_activity': time.time(),
            'context': params.get('context', {})
        }
        
        return {
            "session_id": session_id,
            "name": session_name,
            "created_at": self.sessions[session_id]['created_at']
        }
    
    async def _handle_destroy_session(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle session/destroy request."""
        session_id = params.get('session_id')
        
        if session_id in self.sessions:
            del self.sessions[session_id]
            return {"success": True, "message": f"Session {session_id} destroyed"}
        else:
            raise ValueError(f"Session not found: {session_id}")
    
    def _handle_heartbeat(self, params: Dict[str, Any]):
        """Handle client/heartbeat notification."""
        client_id = params.get('client_id', 'unknown')
        timestamp = params.get('timestamp', time.time())
        
        logger.info(f"Heartbeat from client {client_id} at {timestamp}")
    
    def _handle_metrics_report(self, params: Dict[str, Any]):
        """Handle client metrics report."""
        client_metrics = params.get('metrics', {})
        client_id = params.get('client_id', 'unknown')
        
        logger.info(f"Received metrics from client {client_id}: {client_metrics}")

# Example with custom extensions
def create_extended_server():
    """Create a server with custom protocol extensions."""
    server = ExtendedServer("Extended Calculator", "2.0.0")
    server._start_time = time.time()
    
    # Add standard calculator tools
    server.register_tool(
        "add",
        lambda a, b: a + b,
        "Add two numbers",
        {
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"}
            },
            "required": ["a", "b"]
        }
    )
    
    # Add extended tool with session context
    async def contextual_calculate(operation: str, numbers: List[float], session_id: str = None) -> Dict[str, Any]:
        """Perform calculation with session context."""
        session = None
        if session_id and session_id in server.sessions:
            session = server.sessions[session_id]
            session['last_activity'] = time.time()
        
        # Perform calculation
        if operation == "sum":
            result = sum(numbers)
        elif operation == "product":
            result = 1
            for num in numbers:
                result *= num
        elif operation == "average":
            result = sum(numbers) / len(numbers) if numbers else 0
        else:
            raise ValueError(f"Unknown operation: {operation}")
        
        return {
            "result": result,
            "operation": operation,
            "input_numbers": numbers,
            "session_context": session['context'] if session else None
        }
    
    server.register_tool(
        "contextual_calculate",
        contextual_calculate,
        "Perform calculation with session context",
        {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["sum", "product", "average"]},
                "numbers": {"type": "array", "items": {"type": "number"}},
                "session_id": {"type": "string"}
            },
            "required": ["operation", "numbers"]
        }
    )
    
    return server

if __name__ == "__main__":
    # Run extended server
    server = create_extended_server()
    asyncio.run(server.run_stdio())
```

## Performance optimization

### Concurrent request handling

```python
"""
High-performance server with concurrent request handling.
"""

import asyncio
import time
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import psutil

@dataclass
class PerformanceConfig:
    """Configuration for performance optimizations."""
    max_concurrent_requests: int = 100
    request_timeout: float = 30.0
    thread_pool_size: int = 10
    enable_caching: bool = True
    cache_ttl: float = 300.0  # 5 minutes
    enable_metrics: bool = True

class HighPerformanceServer(LowLevelServer):
    """High-performance MCP server with optimizations."""
    
    def __init__(self, name: str, version: str = "1.0.0", config: PerformanceConfig = None):
        super().__init__(name, version)
        self.config = config or PerformanceConfig()
        
        # Performance components
        self.thread_pool = ThreadPoolExecutor(max_workers=self.config.thread_pool_size)
        self.request_semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.request_queue = asyncio.Queue()
        
        # Metrics
        self.performance_metrics = {
            'requests_per_second': 0,
            'average_response_time': 0,
            'active_requests': 0,
            'cache_hit_rate': 0,
            'queue_size': 0
        }
        
        # Start background tasks
        self._start_background_tasks()
    
    def _start_background_tasks(self):
        """Start background performance monitoring tasks."""
        if self.config.enable_metrics:
            asyncio.create_task(self._metrics_collector())
        if self.config.enable_caching:
            asyncio.create_task(self._cache_cleanup())
    
    async def process_message(self, message) -> Optional[Any]:
        """Process message with performance optimizations."""
        async with self.request_semaphore:
            # Add to queue for metrics
            await self.request_queue.put(time.time())
            
            try:
                # Apply timeout
                return await asyncio.wait_for(
                    self._process_message_internal(message),
                    timeout=self.config.request_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout for method: {getattr(message, 'method', 'unknown')}")
                if hasattr(message, 'id'):
                    return self._create_error_response(message.id, -32603, "Request timeout")
                return None
            finally:
                self.performance_metrics['active_requests'] = self.request_semaphore._value
    
    async def _process_message_internal(self, message):
        """Internal message processing with caching."""
        method = getattr(message, 'method', None)
        params = getattr(message, 'params', {})
        
        # Check cache for read-only operations
        if self.config.enable_caching and method in ['tools/list', 'resources/list', 'prompts/list']:
            cache_key = f"{method}:{hash(str(params))}"
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                return cached_result
        
        # Process message
        start_time = time.time()
        result = await super().process_message(message)
        duration = time.time() - start_time
        
        # Cache result for read-only operations
        if self.config.enable_caching and method in ['tools/list', 'resources/list', 'prompts/list'] and result:
            cache_key = f"{method}:{hash(str(params))}"
            self._cache_result(cache_key, result, duration)
        
        return result
    
    def _get_cached_result(self, cache_key: str) -> Optional[Any]:
        """Get result from cache if valid."""
        if cache_key in self.cache:
            cache_entry = self.cache[cache_key]
            if time.time() - cache_entry['timestamp'] < self.config.cache_ttl:
                return cache_entry['result']
            else:
                del self.cache[cache_key]
        return None
    
    def _cache_result(self, cache_key: str, result: Any, processing_time: float):
        """Cache result with metadata."""
        self.cache[cache_key] = {
            'result': result,
            'timestamp': time.time(),
            'processing_time': processing_time
        }
    
    async def _metrics_collector(self):
        """Collect performance metrics."""
        request_times = []
        
        while True:
            try:
                # Calculate requests per second
                current_time = time.time()
                recent_requests = []
                
                # Drain queue and collect recent requests
                while not self.request_queue.empty():
                    try:
                        request_time = self.request_queue.get_nowait()
                        if current_time - request_time < 60:  # Last minute
                            recent_requests.append(request_time)
                    except asyncio.QueueEmpty:
                        break
                
                # Update metrics
                self.performance_metrics['requests_per_second'] = len(recent_requests) / 60
                self.performance_metrics['queue_size'] = self.request_queue.qsize()
                
                # Calculate cache hit rate
                total_cache_requests = len(self.cache)
                if total_cache_requests > 0:
                    # Simplified cache hit rate calculation
                    valid_cache_entries = sum(
                        1 for entry in self.cache.values()
                        if current_time - entry['timestamp'] < self.config.cache_ttl
                    )
                    self.performance_metrics['cache_hit_rate'] = valid_cache_entries / total_cache_requests
                
                # System metrics
                process = psutil.Process()
                self.performance_metrics.update({
                    'memory_usage_mb': process.memory_info().rss / 1024 / 1024,
                    'cpu_percent': process.cpu_percent(),
                    'thread_count': process.num_threads()
                })
                
                await asyncio.sleep(10)  # Update every 10 seconds
                
            except Exception as e:
                logger.exception(f"Error in metrics collector: {e}")
                await asyncio.sleep(10)
    
    async def _cache_cleanup(self):
        """Clean up expired cache entries."""
        while True:
            try:
                current_time = time.time()
                expired_keys = [
                    key for key, entry in self.cache.items()
                    if current_time - entry['timestamp'] > self.config.cache_ttl
                ]
                
                for key in expired_keys:
                    del self.cache[key]
                
                if expired_keys:
                    logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
                
                await asyncio.sleep(60)  # Cleanup every minute
                
            except Exception as e:
                logger.exception(f"Error in cache cleanup: {e}")
                await asyncio.sleep(60)
    
    def _create_error_response(self, request_id: Any, code: int, message: str):
        """Create JSON-RPC error response."""
        return type('JSONRPCResponse', (), {
            'id': request_id,
            'error': type('JSONRPCError', (), {
                'code': code,
                'message': message
            })()
        })()
    
    # Add performance monitoring tool
    async def _handle_performance_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle performance/stats request."""
        return {
            "performance_metrics": self.performance_metrics,
            "config": {
                "max_concurrent_requests": self.config.max_concurrent_requests,
                "request_timeout": self.config.request_timeout,
                "thread_pool_size": self.config.thread_pool_size,
                "cache_enabled": self.config.enable_caching,
                "cache_ttl": self.config.cache_ttl
            },
            "cache_stats": {
                "total_entries": len(self.cache),
                "memory_usage_estimate": sum(
                    len(str(entry)) for entry in self.cache.values()
                )
            }
        }

# Performance monitoring tool
def add_performance_monitoring(server: HighPerformanceServer):
    """Add performance monitoring tools to server."""
    
    server.request_handlers["performance/stats"] = server._handle_performance_stats
    
    def get_system_info() -> Dict[str, Any]:
        """Get system information."""
        try:
            process = psutil.Process()
            return {
                "cpu_count": psutil.cpu_count(),
                "memory_total_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
                "memory_available_gb": psutil.virtual_memory().available / 1024 / 1024 / 1024,
                "process_memory_mb": process.memory_info().rss / 1024 / 1024,
                "process_cpu_percent": process.cpu_percent(),
                "open_files": len(process.open_files()),
                "connections": len(process.connections())
            }
        except Exception as e:
            return {"error": str(e)}
    
    server.register_tool(
        "system_info",
        get_system_info,
        "Get system resource information",
        {"type": "object", "properties": {}}
    )

# Usage example
def create_high_performance_server():
    """Create high-performance server."""
    config = PerformanceConfig(
        max_concurrent_requests=200,
        request_timeout=60.0,
        thread_pool_size=20,
        enable_caching=True,
        cache_ttl=600.0
    )
    
    server = HighPerformanceServer("High Performance Calculator", "3.0.0", config)
    add_performance_monitoring(server)
    
    # Add CPU-intensive tool
    def fibonacci(n: int) -> int:
        """Calculate Fibonacci number (CPU intensive)."""
        if n <= 1:
            return n
        return fibonacci(n - 1) + fibonacci(n - 2)
    
    server.register_tool(
        "fibonacci",
        fibonacci,
        "Calculate Fibonacci number (CPU intensive)",
        {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "minimum": 0, "maximum": 35}
            },
            "required": ["n"]
        }
    )
    
    return server

if __name__ == "__main__":
    server = create_high_performance_server()
    asyncio.run(server.run_stdio())
```

## Best practices

### Architecture guidelines

- **Separation of concerns** - Keep protocol handling separate from business logic
- **Error boundaries** - Implement comprehensive error handling at each layer
- **Resource management** - Properly manage connections, memory, and file handles
- **Monitoring** - Add metrics and logging for production deployments
- **Testing** - Unit test individual handlers and integration test full workflows

### Security considerations

- **Input validation** - Validate all incoming parameters
- **Rate limiting** - Prevent abuse with request rate limits
- **Authentication** - Implement proper authentication for sensitive operations
- **Logging** - Log security events and access attempts
- **Resource limits** - Set limits on computation and memory usage

### Performance optimization

- **Async operations** - Use async/await throughout
- **Connection pooling** - Pool database and external service connections
- **Caching** - Cache expensive computations and frequently accessed data
- **Concurrency limits** - Prevent resource exhaustion with semaphores
- **Monitoring** - Track performance metrics and optimize bottlenecks

## Next steps

- **[Structured output](structured-output.md)** - Advanced output formatting
- **[Completions](completions.md)** - LLM integration patterns
- **[Authentication](authentication.md)** - Server security implementation
- **[Streamable HTTP](streamable-http.md)** - Modern transport details