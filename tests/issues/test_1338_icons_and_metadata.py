"""Test icon and metadata support (SEP-973)."""

import pytest

from mcp.server.fastmcp import FastMCP
from mcp.types import Icon

pytestmark = pytest.mark.anyio


async def test_icons_and_website_url():
    """Test that icons and websiteUrl are properly returned in API calls."""

    # Create test icon
    test_icon = Icon(
        src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
        mimeType="image/png",
        sizes=["1x1"],
    )

    # Create server with website URL and icon
    mcp = FastMCP("TestServer", website_url="https://example.com", icons=[test_icon])

    # Create tool with icon
    @mcp.tool(icons=[test_icon])
    def test_tool(message: str) -> str:
        """A test tool with an icon."""
        return message

    # Create resource with icon
    @mcp.resource("test://resource", icons=[test_icon])
    def test_resource() -> str:
        """A test resource with an icon."""
        return "test content"

    # Create prompt with icon
    @mcp.prompt("test_prompt", icons=[test_icon])
    def test_prompt(text: str) -> str:
        """A test prompt with an icon."""
        return text

    # Create resource template with icon
    @mcp.resource("test://weather/{city}", icons=[test_icon])
    def test_resource_template(city: str) -> str:
        """Get weather for a city."""
        return f"Weather for {city}"

    # Test server metadata includes websiteUrl and icons
    assert mcp.name == "TestServer"
    assert mcp.website_url == "https://example.com"
    assert mcp.icons is not None
    assert len(mcp.icons) == 1
    assert mcp.icons[0].src == test_icon.src
    assert mcp.icons[0].mimeType == test_icon.mimeType
    assert mcp.icons[0].sizes == test_icon.sizes

    # Test tool includes icon
    tools = await mcp.list_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "test_tool"
    assert tool.icons is not None
    assert len(tool.icons) == 1
    assert tool.icons[0].src == test_icon.src

    # Test resource includes icon
    resources = await mcp.list_resources()
    assert len(resources) == 1
    resource = resources[0]
    assert str(resource.uri) == "test://resource"
    assert resource.icons is not None
    assert len(resource.icons) == 1
    assert resource.icons[0].src == test_icon.src

    # Test prompt includes icon
    prompts = await mcp.list_prompts()
    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.name == "test_prompt"
    assert prompt.icons is not None
    assert len(prompt.icons) == 1
    assert prompt.icons[0].src == test_icon.src

    # Test resource template includes icon
    templates = await mcp.list_resource_templates()
    assert len(templates) == 1
    template = templates[0]
    assert template.name == "test_resource_template"
    assert template.uriTemplate == "test://weather/{city}"
    assert template.icons is not None
    assert len(template.icons) == 1
    assert template.icons[0].src == test_icon.src


async def test_multiple_icons():
    """Test that multiple icons can be added to tools, resources, and prompts."""

    # Create multiple test icons
    icon1 = Icon(src="data:image/png;base64,icon1", mimeType="image/png", sizes=["16x16"])
    icon2 = Icon(src="data:image/png;base64,icon2", mimeType="image/png", sizes=["32x32"])
    icon3 = Icon(src="data:image/png;base64,icon3", mimeType="image/png", sizes=["64x64"])

    mcp = FastMCP("MultiIconServer")

    # Create tool with multiple icons
    @mcp.tool(icons=[icon1, icon2, icon3])
    def multi_icon_tool() -> str:
        """A tool with multiple icons."""
        return "success"

    # Test tool has all icons
    tools = await mcp.list_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.icons is not None
    assert len(tool.icons) == 3
    assert tool.icons[0].sizes == ["16x16"]
    assert tool.icons[1].sizes == ["32x32"]
    assert tool.icons[2].sizes == ["64x64"]


async def test_no_icons_or_website():
    """Test that server works without icons or websiteUrl."""

    mcp = FastMCP("BasicServer")

    @mcp.tool()
    def basic_tool() -> str:
        """A basic tool without icons."""
        return "success"

    # Test server metadata has no websiteUrl or icons
    assert mcp.name == "BasicServer"
    assert mcp.website_url is None
    assert mcp.icons is None

    # Test tool has no icons
    tools = await mcp.list_tools()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "basic_tool"
    assert tool.icons is None
