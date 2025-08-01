"""Tests for resource inheritance model."""

import json

import pytest

from mcp.server.fastmcp.prompts import Prompt
from mcp.server.fastmcp.resources import ResourceManager
from mcp.server.fastmcp.tools import Tool
from mcp.types import ToolAnnotations

pytestmark = pytest.mark.anyio


@pytest.fixture
def resource_manager():
    """Create a resource manager for testing."""
    return ResourceManager()


@pytest.fixture
def sample_tool():
    """Create a sample tool for testing."""

    def add_numbers(a: int, b: int) -> int:
        """Add two numbers together."""
        return a + b

    return Tool.from_function(
        add_numbers,
        name="add",
        title="Add Numbers",
        description="Adds two numbers together",
        annotations=ToolAnnotations(),
    )


@pytest.fixture
def sample_prompt():
    """Create a sample prompt for testing."""

    def greeting_prompt(name: str) -> str:
        """Generate a greeting message."""
        return f"Hello, {name}!"

    return Prompt.from_function(
        greeting_prompt,
        name="greeting",
        title="Greeting Prompt",
        description="Generates a personalized greeting",
    )


class TestToolInheritance:
    """Tests for Tool inheriting from Resource."""

    def test_tool_is_resource(self, sample_tool):
        """Test that Tool inherits from Resource."""
        # Tool should have URI automatically generated
        assert str(sample_tool.uri) == "tool://add"
        assert sample_tool.name == "add"
        assert sample_tool.title == "Add Numbers"
        assert sample_tool.description == "Adds two numbers together"
        assert sample_tool.mime_type == "application/json"

    async def test_tool_read_method(self, sample_tool):
        """Test reading tool schema via Resource interface."""
        content = await sample_tool.read()

        data = json.loads(content)
        assert data["name"] == "add"
        assert data["title"] == "Add Numbers"
        assert data["description"] == "Adds two numbers together"
        assert "parameters" in data
        # Check that annotations are included (but empty in this case)
        assert "annotations" in data
        assert data["annotations"] == {}


class TestPromptInheritance:
    """Tests for Prompt inheriting from Resource."""

    def test_prompt_is_resource(self, sample_prompt):
        """Test that Prompt inherits from Resource."""
        # Prompt should have URI automatically generated
        assert str(sample_prompt.uri) == "prompt://greeting"
        assert sample_prompt.name == "greeting"
        assert sample_prompt.title == "Greeting Prompt"
        assert sample_prompt.description == "Generates a personalized greeting"
        assert sample_prompt.mime_type == "application/json"

    async def test_prompt_read_method(self, sample_prompt):
        """Test reading prompt info via Resource interface."""
        content = await sample_prompt.read()

        data = json.loads(content)
        assert data["name"] == "greeting"
        assert data["title"] == "Greeting Prompt"
        assert data["description"] == "Generates a personalized greeting"
        assert len(data["arguments"]) == 1
        assert data["arguments"][0]["name"] == "name"
        assert data["arguments"][0]["required"] is True


class TestResourceManagerIntegration:
    """Tests for ResourceManager with inheritance model."""

    async def test_tool_as_resource_lookup(self, resource_manager, sample_tool):
        """Test that tools can be accessed as resources."""
        # Add tool directly - it's already a resource
        resource_manager.add_resource(sample_tool)

        # Should be able to get it by URI
        retrieved = await resource_manager.get_resource("tool://add")
        assert retrieved is not None
        assert isinstance(retrieved, Tool)

        # Read the content
        content = await retrieved.read()
        data = json.loads(content)
        assert data["name"] == "add"

    async def test_prompt_as_resource_lookup(self, resource_manager, sample_prompt):
        """Test that prompts can be accessed as resources."""
        # Add prompt directly - it's already a resource
        resource_manager.add_resource(sample_prompt)

        # Should be able to get it by URI
        retrieved = await resource_manager.get_resource("prompt://greeting")
        assert retrieved is not None
        assert isinstance(retrieved, Prompt)

        # Read the content
        content = await retrieved.read()
        data = json.loads(content)
        assert data["name"] == "greeting"

    def test_list_resources_filters_tools_and_prompts(self, resource_manager, sample_tool, sample_prompt):
        """Test that list_resources filters out tool/prompt resources."""
        from mcp.server.fastmcp.resources import TextResource

        # Add regular resource
        from pydantic import AnyUrl
        text_resource = TextResource(uri=AnyUrl("file://test.txt"), name="test.txt", text="Hello world")
        resource_manager.add_resource(text_resource)

        # Add tool and prompt as resources
        resource_manager.add_resource(sample_tool)
        resource_manager.add_resource(sample_prompt)

        # List should only include the text resource
        resources = resource_manager.list_resources()
        assert len(resources) == 1
        assert resources[0].uri == text_resource.uri

        # But we can still access tools/prompts by URI
        assert resource_manager._resources.get("tool://add") is not None
        assert resource_manager._resources.get("prompt://greeting") is not None
