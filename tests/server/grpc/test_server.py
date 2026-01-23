
import asyncio
import pytest
from pydantic import AnyUrl
from mcp.server.lowlevel.server import Server
from mcp.client.grpc import GrpcClientTransport
from mcp.server.grpc import start_grpc_server
import mcp.types as types
from mcp.server.lowlevel.helper_types import ReadResourceContents

@pytest.mark.anyio
async def test_grpc_server_end_to_end():
    # 1. Setup Server
    server = Server("test-grpc-server")
    
    @server.call_tool()
    async def echo_tool(name: str, arguments: dict) -> list[types.TextContent]:
        if name != "echo_tool":
            raise ValueError(f"Unknown tool: {name}")
        
        # If progress is requested, send some notifications
        ctx = server.request_context
        if ctx.session:
            await ctx.session.send_progress_notification(
                progress_token=123,
                progress=50.0,
                total=100.0,
                message="Halfway there"
            )

        return [types.TextContent(type="text", text=f"Echo: {arguments.get('message', '')}")]

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="echo_tool", 
                description="Echoes back", 
                inputSchema={"type": "object", "properties": {"message": {"type": "string"}}}
            )
        ]

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl("file:///test/resource.txt"),
                name="test_resource",
                mimeType="text/plain"
            )
        ]

    @server.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        if str(uri) == "file:///test/resource.txt":
            return [
                ReadResourceContents(
                    content="Resource Content",
                    mime_type="text/plain"
                )
            ]
        raise ValueError("Resource not found")

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        return [
            types.Prompt(
                name="test_prompt",
                description="A test prompt"
            )
        ]

    @server.get_prompt()
    async def get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
        if name == "test_prompt":
            return types.GetPromptResult(
                description="A test prompt",
                messages=[
                    types.PromptMessage(
                        role="user",
                        content=types.TextContent(type="text", text="Hello Prompt")
                    )
                ]
            )
        raise ValueError("Prompt not found")

    # 2. Start gRPC Server
    import socket
    sock = socket.socket()
    sock.bind(('localhost', 0))
    port = sock.getsockname()[1]
    sock.close()
    
    address = f"localhost:{port}"
    grpc_server = await start_grpc_server(server, address)
    
    try:
        # 3. Connect Client
        async with GrpcClientTransport(address) as client:
            # Test Initialize
            init_res = await client.initialize()
            assert init_res.serverInfo.name == "test-grpc-server"
            
            # Test List Tools (Streaming)
            tools_res = await client.list_tools()
            assert len(tools_res.tools) == 1
            assert tools_res.tools[0].name == "echo_tool"
            
            # Test Call Tool
            call_res = await client.call_tool("echo_tool", {"message": "Hello gRPC"})
            assert call_res.content[0].text == "Echo: Hello gRPC"

            # Test Call Tool with Progress
            progress_updates = []
            async def progress_callback(progress, total, message):
                progress_updates.append((progress, total, message))
            
            call_res_progress = await client.call_tool(
                "echo_tool", 
                {"message": "Hello Progress"},
                progress_callback=progress_callback
            )
            assert call_res_progress.content[0].text == "Echo: Hello Progress"
            assert len(progress_updates) == 1
            assert progress_updates[0] == (50.0, 100.0, "Halfway there")

            # Test Error (Tool not found)
            # MCP returns error as result, not exception
            error_res = await client.call_tool("non_existent_tool", {})
            assert error_res.isError is True
            assert "Unknown tool" in error_res.content[0].text

            # Ensure connection is still healthy after an error
            call_res = await client.call_tool("echo_tool", {"message": "Still here"})
            assert call_res.content[0].text == "Echo: Still here"

            # Test List Resources (Streaming)
            res_list = await client.list_resources()
            assert len(res_list.resources) == 1
            assert str(res_list.resources[0].uri) == "file:///test/resource.txt"

            # Test Read Resource
            read_res = await client.read_resource(AnyUrl("file:///test/resource.txt"))
            assert read_res.contents[0].text == "Resource Content"

            # Test Read Resource error
            with pytest.raises(Exception) as excinfo:
                await client.read_resource(AnyUrl("file:///test/non_existent.txt"))
            assert "Resource not found" in str(excinfo.value)

            # Test List Prompts (Streaming)
            prompts_list = await client.list_prompts()
            assert len(prompts_list.prompts) == 1
            assert prompts_list.prompts[0].name == "test_prompt"

            # Test Get Prompt
            prompt_res = await client.get_prompt("test_prompt")
            assert prompt_res.messages[0].content.text == "Hello Prompt"
            
    finally:
        await grpc_server.stop(0)
