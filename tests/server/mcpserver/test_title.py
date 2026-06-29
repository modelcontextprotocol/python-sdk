import pytest
from mcp_types import Prompt, Resource, ResourceTemplate, Tool, ToolAnnotations

from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from mcp.shared.metadata_utils import get_display_name


@pytest.mark.anyio
async def test_server_name_title_description_version():
    mcp = MCPServer(
        name="TestServer",
        title="Test Server Title",
        description="This is a test server description.",
        version="1.0",
    )

    assert mcp.title == "Test Server Title"
    assert mcp.description == "This is a test server description."
    assert mcp.version == "1.0"

    async with Client(mcp) as client:
        assert client.server_info.name == "TestServer"
        assert client.server_info.title == "Test Server Title"
        assert client.server_info.description == "This is a test server description."
        assert client.server_info.version == "1.0"


@pytest.mark.anyio
async def test_tool_title_precedence():
    mcp = MCPServer(name="TitleTestServer")

    @mcp.tool(description="Basic tool")
    def basic_tool(message: str) -> str:  # pragma: no cover
        return message

    @mcp.tool(description="Tool with title", title="User-Friendly Tool")
    def tool_with_title(message: str) -> str:  # pragma: no cover
        return message

    @mcp.tool(description="Tool with annotations")
    def tool_with_annotations(message: str) -> str:  # pragma: no cover
        return message

    @mcp.tool(description="Tool with both", title="Primary Title")
    def tool_with_both(message: str) -> str:  # pragma: no cover
        return message

    async with Client(mcp) as client:
        tools_result = await client.list_tools()
        tools = {tool.name: tool for tool in tools_result.tools}

        assert "basic_tool" in tools
        basic = tools["basic_tool"]
        assert basic.title is None
        assert basic.name == "basic_tool"

        assert "tool_with_title" in tools
        titled = tools["tool_with_title"]
        assert titled.title == "User-Friendly Tool"

        assert "tool_with_both" in tools
        both = tools["tool_with_both"]
        assert both.title == "Primary Title"


@pytest.mark.anyio
async def test_prompt_title():
    mcp = MCPServer(name="PromptTitleServer")

    @mcp.prompt(description="Basic prompt")
    def basic_prompt(topic: str) -> str:  # pragma: no cover
        return f"Tell me about {topic}"

    @mcp.prompt(description="Titled prompt", title="Ask About Topic")
    def titled_prompt(topic: str) -> str:  # pragma: no cover
        return f"Tell me about {topic}"

    async with Client(mcp) as client:
        prompts_result = await client.list_prompts()
        prompts = {prompt.name: prompt for prompt in prompts_result.prompts}

        assert "basic_prompt" in prompts
        basic = prompts["basic_prompt"]
        assert basic.title is None
        assert basic.name == "basic_prompt"

        assert "titled_prompt" in prompts
        titled = prompts["titled_prompt"]
        assert titled.title == "Ask About Topic"


@pytest.mark.anyio
async def test_resource_title():
    mcp = MCPServer(name="ResourceTitleServer")

    def get_basic_data() -> str:  # pragma: no cover
        return "Basic data"

    basic_resource = FunctionResource(
        uri="resource://basic",
        name="basic_resource",
        description="Basic resource",
        fn=get_basic_data,
    )
    mcp.add_resource(basic_resource)

    def get_titled_data() -> str:  # pragma: no cover
        return "Titled data"

    titled_resource = FunctionResource(
        uri="resource://titled",
        name="titled_resource",
        title="User-Friendly Resource",
        description="Resource with title",
        fn=get_titled_data,
    )
    mcp.add_resource(titled_resource)

    @mcp.resource("resource://dynamic/{id}")
    def dynamic_resource(id: str) -> str:  # pragma: no cover
        return f"Data for {id}"

    @mcp.resource("resource://titled-dynamic/{id}", title="Dynamic Data")
    def titled_dynamic_resource(id: str) -> str:  # pragma: no cover
        return f"Data for {id}"

    async with Client(mcp) as client:
        resources_result = await client.list_resources()
        resources = {str(res.uri): res for res in resources_result.resources}

        assert "resource://basic" in resources
        basic = resources["resource://basic"]
        assert basic.title is None
        assert basic.name == "basic_resource"

        assert "resource://titled" in resources
        titled = resources["resource://titled"]
        assert titled.title == "User-Friendly Resource"

        templates_result = await client.list_resource_templates()
        templates = {tpl.uri_template: tpl for tpl in templates_result.resource_templates}

        assert "resource://dynamic/{id}" in templates
        dynamic = templates["resource://dynamic/{id}"]
        assert dynamic.title is None
        assert dynamic.name == "dynamic_resource"

        if "resource://titled-dynamic/{id}" in templates:  # pragma: no branch
            titled_dynamic = templates["resource://titled-dynamic/{id}"]
            assert titled_dynamic.title == "Dynamic Data"


@pytest.mark.anyio
async def test_get_display_name_utility():
    # Tool precedence: title > annotations.title > name
    tool_name_only = Tool(name="test_tool", input_schema={})
    assert get_display_name(tool_name_only) == "test_tool"

    tool_with_title = Tool(name="test_tool", title="Test Tool", input_schema={})
    assert get_display_name(tool_with_title) == "Test Tool"

    tool_with_annotations = Tool(name="test_tool", input_schema={}, annotations=ToolAnnotations(title="Annotated Tool"))
    assert get_display_name(tool_with_annotations) == "Annotated Tool"

    tool_with_both = Tool(
        name="test_tool", title="Primary Title", input_schema={}, annotations=ToolAnnotations(title="Secondary Title")
    )
    assert get_display_name(tool_with_both) == "Primary Title"

    # Other types: title > name
    resource = Resource(uri="file://test", name="test_res")
    assert get_display_name(resource) == "test_res"

    resource_with_title = Resource(uri="file://test", name="test_res", title="Test Resource")
    assert get_display_name(resource_with_title) == "Test Resource"

    prompt = Prompt(name="test_prompt")
    assert get_display_name(prompt) == "test_prompt"

    prompt_with_title = Prompt(name="test_prompt", title="Test Prompt")
    assert get_display_name(prompt_with_title) == "Test Prompt"

    template = ResourceTemplate(uri_template="file://{id}", name="test_template")
    assert get_display_name(template) == "test_template"

    template_with_title = ResourceTemplate(uri_template="file://{id}", name="test_template", title="Test Template")
    assert get_display_name(template_with_title) == "Test Template"
