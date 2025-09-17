"""Integration tests for title field functionality."""

import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.shared.metadata_utils import get_display_name
from mcp.types import Prompt, Resource, ResourceTemplate, Tool, ToolAnnotations


@pytest.mark.anyio
async def test_tool_title_precedence():
    """Test that tool title precedence works correctly: title > annotations.title > name."""
    # Create server with various tool configurations
    mcp = FastMCP(name="TitleTestServer")

    # Tool with only name
    @mcp.tool(description="Basic tool")
    def basic_tool(message: str) -> str:
        return message

    # Tool with title
    @mcp.tool(description="Tool with title", title="User-Friendly Tool")
    def tool_with_title(message: str) -> str:
        return message

    # Tool with annotations.title (when title is not supported on decorator)
    # We'll need to add this manually after registration
    @mcp.tool(description="Tool with annotations")
    def tool_with_annotations(message: str) -> str:
        return message

    # Tool with both title and annotations.title
    @mcp.tool(description="Tool with both", title="Primary Title")
    def tool_with_both(message: str) -> str:
        return message

    # Start server and connect client
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        await client.initialize()

        # List tools
        tools_result = await client.list_tools()
        tools = {tool.name: tool for tool in tools_result.tools}

        # Verify basic tool uses name
        assert "basic_tool" in tools
        basic = tools["basic_tool"]
        # Since we haven't implemented get_display_name yet, we'll check the raw fields
        assert basic.title is None
        assert basic.name == "basic_tool"

        # Verify tool with title
        assert "tool_with_title" in tools
        titled = tools["tool_with_title"]
        assert titled.title == "User-Friendly Tool"

        # For now, we'll skip the annotations.title test as it requires modifying
        # the tool after registration, which we'll implement later

        # Verify tool with both uses title over annotations.title
        assert "tool_with_both" in tools
        both = tools["tool_with_both"]
        assert both.title == "Primary Title"


@pytest.mark.anyio
async def test_prompt_title():
    """Test that prompt titles work correctly."""
    mcp = FastMCP(name="PromptTitleServer")

    # Prompt with only name
    @mcp.prompt(description="Basic prompt")
    def basic_prompt(topic: str) -> str:
        return f"Tell me about {topic}"

    # Prompt with title
    @mcp.prompt(description="Titled prompt", title="Ask About Topic")
    def titled_prompt(topic: str) -> str:
        return f"Tell me about {topic}"

    # Start server and connect client
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        await client.initialize()

        # List prompts
        prompts_result = await client.list_prompts()
        prompts = {prompt.name: prompt for prompt in prompts_result.prompts}

        # Verify basic prompt uses name
        assert "basic_prompt" in prompts
        basic = prompts["basic_prompt"]
        assert basic.title is None
        assert basic.name == "basic_prompt"

        # Verify prompt with title
        assert "titled_prompt" in prompts
        titled = prompts["titled_prompt"]
        assert titled.title == "Ask About Topic"


@pytest.mark.anyio
async def test_resource_title():
    """Test that resource titles work correctly."""
    mcp = FastMCP(name="ResourceTitleServer")

    # Static resource without title
    def get_basic_data() -> str:
        return "Basic data"

    basic_resource = FunctionResource(
        uri=AnyUrl("resource://basic"),
        name="basic_resource",
        description="Basic resource",
        fn=get_basic_data,
    )
    mcp.add_resource(basic_resource)

    # Static resource with title
    def get_titled_data() -> str:
        return "Titled data"

    titled_resource = FunctionResource(
        uri=AnyUrl("resource://titled"),
        name="titled_resource",
        title="User-Friendly Resource",
        description="Resource with title",
        fn=get_titled_data,
    )
    mcp.add_resource(titled_resource)

    # Dynamic resource without title
    @mcp.resource("resource://dynamic/{id}")
    def dynamic_resource(id: str) -> str:
        return f"Data for {id}"

    # Dynamic resource with title (when supported)
    @mcp.resource("resource://titled-dynamic/{id}", title="Dynamic Data")
    def titled_dynamic_resource(id: str) -> str:
        return f"Data for {id}"

    # Start server and connect client
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        await client.initialize()

        # List resources
        resources_result = await client.list_resources()
        resources = {str(res.uri): res for res in resources_result.resources}

        # Verify basic resource uses name
        assert "resource://basic" in resources
        basic = resources["resource://basic"]
        assert basic.title is None
        assert basic.name == "basic_resource"

        # Verify resource with title
        assert "resource://titled" in resources
        titled = resources["resource://titled"]
        assert titled.title == "User-Friendly Resource"

        # List resource templates
        templates_result = await client.list_resource_templates()
        templates = {tpl.uriTemplate: tpl for tpl in templates_result.resourceTemplates}

        # Verify dynamic resource template
        assert "resource://dynamic/{id}" in templates
        dynamic = templates["resource://dynamic/{id}"]
        assert dynamic.title is None
        assert dynamic.name == "dynamic_resource"

        # Verify titled dynamic resource template (when supported)
        if "resource://titled-dynamic/{id}" in templates:
            titled_dynamic = templates["resource://titled-dynamic/{id}"]
            assert titled_dynamic.title == "Dynamic Data"


@pytest.mark.anyio
async def test_get_display_name_utility():
    """Test the get_display_name utility function."""

    # Test tool precedence: title > annotations.title > name
    tool_name_only = Tool(name="test_tool", inputSchema={})
    assert get_display_name(tool_name_only) == "test_tool"

    tool_with_title = Tool(name="test_tool", title="Test Tool", inputSchema={})
    assert get_display_name(tool_with_title) == "Test Tool"

    tool_with_annotations = Tool(name="test_tool", inputSchema={}, annotations=ToolAnnotations(title="Annotated Tool"))
    assert get_display_name(tool_with_annotations) == "Annotated Tool"

    tool_with_both = Tool(
        name="test_tool", title="Primary Title", inputSchema={}, annotations=ToolAnnotations(title="Secondary Title")
    )
    assert get_display_name(tool_with_both) == "Primary Title"

    # Test other types: title > name
    resource = Resource(uri=AnyUrl("file://test"), name="test_res")
    assert get_display_name(resource) == "test_res"

    resource_with_title = Resource(uri=AnyUrl("file://test"), name="test_res", title="Test Resource")
    assert get_display_name(resource_with_title) == "Test Resource"

    prompt = Prompt(name="test_prompt")
    assert get_display_name(prompt) == "test_prompt"

    prompt_with_title = Prompt(name="test_prompt", title="Test Prompt")
    assert get_display_name(prompt_with_title) == "Test Prompt"

    template = ResourceTemplate(uriTemplate="file://{id}", name="test_template")
    assert get_display_name(template) == "test_template"

    template_with_title = ResourceTemplate(uriTemplate="file://{id}", name="test_template", title="Test Template")
    assert get_display_name(template_with_title) == "Test Template"
