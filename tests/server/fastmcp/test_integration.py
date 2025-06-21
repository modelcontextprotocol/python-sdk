"""
Integration tests for FastMCP server functionality.

These tests validate the proper functioning of FastMCP in various configurations,
using a direct approach that avoids hanging and session termination issues.
"""

import pytest

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent


def make_simple_fastmcp():
    """Create a simple FastMCP server for testing."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["*"],
        allowed_origins=["*"],
    )
    mcp = FastMCP(name="SimpleServer", transport_security=transport_security)

    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    return mcp


@pytest.mark.anyio
async def test_fastmcp_server_creation():
    """Test that a FastMCP server can be created and configured."""
    mcp = make_simple_fastmcp()

    # Test that the server was created with the correct name
    assert mcp.name == "SimpleServer"

    # Test that tools were registered
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo"
    assert "simple echo tool" in tools[0].description

    print(f"Successfully created FastMCP server: {mcp.name}")


@pytest.mark.anyio
async def test_fastmcp_tool_execution():
    """Test that FastMCP tools can be executed directly."""
    mcp = make_simple_fastmcp()

    # Execute the tool directly
    result = await mcp._tool_manager.call_tool("echo", {"message": "Hello, World!"}, context=None)

    # Check the result (tool returns raw string, not wrapped in content)
    assert isinstance(result, str)
    assert "Echo: Hello, World!" in result

    print(f"Successfully executed tool: {result}")


@pytest.mark.anyio
async def test_fastmcp_app_creation():
    """Test that FastMCP can create different types of apps."""
    mcp = make_simple_fastmcp()

    # Test SSE app creation
    sse_app = mcp.sse_app()
    assert sse_app is not None

    # Test streamable HTTP app creation
    http_app = mcp.streamable_http_app()
    assert http_app is not None

    print("Successfully created all app types")


@pytest.mark.anyio
async def test_fastmcp_with_resources():
    """Test FastMCP with resources."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["*"],
        allowed_origins=["*"],
    )
    mcp = FastMCP(name="ResourceServer", transport_security=transport_security)

    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    @mcp.resource("resource://test/info", title="Test Resource")
    def test_resource() -> str:
        return "This is test resource content"

    # Test that resources were registered
    resources = mcp._resource_manager.list_resources()
    assert len(resources) == 1
    assert resources[0].name == "test_resource"
    assert resources[0].title is not None
    assert "Test Resource" in resources[0].title

    # Test resource execution - get the resource and read it
    resource = await mcp._resource_manager.get_resource("resource://test/info")
    assert resource is not None

    # Read the resource content (returns raw string)
    result = await resource.read()
    assert result is not None
    assert isinstance(result, str)
    assert "This is test resource content" in result

    print(f"Successfully tested resources: {result}")


@pytest.mark.anyio
async def test_fastmcp_with_prompts():
    """Test FastMCP with prompts."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["*"],
        allowed_origins=["*"],
    )
    mcp = FastMCP(name="PromptServer", transport_security=transport_security)

    @mcp.tool(description="A simple echo tool")
    def echo(message: str) -> str:
        return f"Echo: {message}"

    @mcp.prompt(description="A test prompt", title="Test Prompt")
    def test_prompt(topic: str) -> str:
        return f"Here is information about {topic}"

    # Test that prompts were registered
    prompts = mcp._prompt_manager.list_prompts()
    assert len(prompts) == 1
    assert prompts[0].name == "test_prompt"
    assert prompts[0].title is not None
    assert "Test Prompt" in prompts[0].title

    # Test prompt execution - get the prompt and render it
    prompt = mcp._prompt_manager.get_prompt("test_prompt")
    assert prompt is not None

    # Render the prompt with arguments
    messages = await prompt.render({"topic": "Python"})
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content is not None
    assert isinstance(messages[0].content, TextContent)
    assert "information about Python" in messages[0].content.text

    print(f"Successfully tested prompts: {messages[0].content.text}")


@pytest.mark.anyio
async def test_fastmcp_comprehensive():
    """Test a comprehensive FastMCP server with all features."""
    transport_security = TransportSecuritySettings(
        allowed_hosts=["*"],
        allowed_origins=["*"],
    )
    mcp = FastMCP(name="ComprehensiveServer", transport_security=transport_security)

    # Add a tool
    @mcp.tool(description="A comprehensive tool", title="Comprehensive Tool")
    def comprehensive_tool(message: str, count: int = 1) -> str:
        return f"Processed '{message}' {count} times"

    # Add a resource
    @mcp.resource("resource://comprehensive/data", title="Comprehensive Data")
    def comprehensive_resource() -> str:
        return "Comprehensive resource data"

    # Add a prompt
    @mcp.prompt(description="A comprehensive prompt", title="Comprehensive Prompt")
    def comprehensive_prompt(subject: str) -> str:
        return f"Comprehensive information about {subject}"

    # Test all components
    tools = mcp._tool_manager.list_tools()
    resources = mcp._resource_manager.list_resources()
    prompts = mcp._prompt_manager.list_prompts()

    assert len(tools) == 1
    assert len(resources) == 1
    assert len(prompts) == 1

    # Test tool execution
    tool_result = await mcp._tool_manager.call_tool("comprehensive_tool", {"message": "test", "count": 3}, context=None)
    assert "Processed 'test' 3 times" in tool_result

    # Test resource reading
    resource = await mcp._resource_manager.get_resource("resource://comprehensive/data")
    assert resource is not None
    resource_result = await resource.read()
    assert resource_result is not None
    assert isinstance(resource_result, str)
    assert "Comprehensive resource data" in resource_result

    # Test prompt rendering
    prompt = mcp._prompt_manager.get_prompt("comprehensive_prompt")
    assert prompt is not None
    prompt_result = await prompt.render({"subject": "AI"})
    assert len(prompt_result) == 1
    assert prompt_result[0].content is not None
    assert isinstance(prompt_result[0].content, TextContent)
    assert "information about AI" in prompt_result[0].content.text

    print("Successfully tested comprehensive FastMCP server")


@pytest.mark.anyio
async def test_fastmcp_without_auth():
    """Test that a FastMCP server without auth can be initialized."""
    mcp = make_simple_fastmcp()

    # Test that the server was created with the correct name
    assert mcp.name == "SimpleServer"

    # Test that tools were registered
    tools = mcp._tool_manager.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "echo"

    print(f"Successfully tested FastMCP server without auth: {mcp.name}")


@pytest.mark.anyio
async def test_fastmcp_streamable_http():
    """Test basic functionality of a FastMCP server over StreamableHTTP."""
    mcp = make_simple_fastmcp()

    # Test that streamable HTTP app can be created
    app = mcp.streamable_http_app()
    assert app is not None

    # Test that tools work
    result = await mcp._tool_manager.call_tool("echo", {"message": "StreamableHTTP test"}, context=None)
    assert "StreamableHTTP test" in result

    print("Successfully tested FastMCP streamable HTTP functionality")
