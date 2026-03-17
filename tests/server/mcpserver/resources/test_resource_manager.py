from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
from pydantic import AnyUrl

from mcp.server.mcpserver.resources import FileResource, FunctionResource, ResourceManager
from tests.server.mcpserver.conftest import MakeContext


@pytest.fixture
def temp_file():
    """Create a temporary file for testing.

    File is automatically cleaned up after the test if it still exists.
    """
    content = "test content"
    with NamedTemporaryFile(mode="w", delete=False) as f:
        f.write(content)
        path = Path(f.name).resolve()
    yield path
    try:  # pragma: lax no cover
        path.unlink()
    except FileNotFoundError:  # pragma: lax no cover
        pass  # File was already deleted by the test


class TestResourceManager:
    """Test ResourceManager functionality."""

    def test_add_resource(self, temp_file: Path):
        """Test adding a resource."""
        manager = ResourceManager()
        resource = FileResource(
            uri=f"file://{temp_file}",
            name="test",
            path=temp_file,
        )
        added = manager.add_resource(resource)
        assert added == resource
        assert manager.list_resources() == [resource]

    def test_add_duplicate_resource(self, temp_file: Path):
        """Test adding the same resource twice."""
        manager = ResourceManager()
        resource = FileResource(
            uri=f"file://{temp_file}",
            name="test",
            path=temp_file,
        )
        first = manager.add_resource(resource)
        second = manager.add_resource(resource)
        assert first == second
        assert manager.list_resources() == [resource]

    def test_warn_on_duplicate_resources(self, temp_file: Path, caplog: pytest.LogCaptureFixture):
        """Test warning on duplicate resources."""
        manager = ResourceManager()
        resource = FileResource(
            uri=f"file://{temp_file}",
            name="test",
            path=temp_file,
        )
        manager.add_resource(resource)
        manager.add_resource(resource)
        assert "Resource already exists" in caplog.text

    def test_disable_warn_on_duplicate_resources(self, temp_file: Path, caplog: pytest.LogCaptureFixture):
        """Test disabling warning on duplicate resources."""
        manager = ResourceManager(warn_on_duplicate_resources=False)
        resource = FileResource(
            uri=f"file://{temp_file}",
            name="test",
            path=temp_file,
        )
        manager.add_resource(resource)
        manager.add_resource(resource)
        assert "Resource already exists" not in caplog.text

    @pytest.mark.anyio
    async def test_get_resource(self, temp_file: Path, make_context: MakeContext):
        """Test getting a resource by URI."""
        manager = ResourceManager()
        resource = FileResource(
            uri=f"file://{temp_file}",
            name="test",
            path=temp_file,
        )
        manager.add_resource(resource)
        retrieved = await manager.get_resource(resource.uri, make_context())
        assert retrieved == resource

    @pytest.mark.anyio
    async def test_get_resource_from_template(self, make_context: MakeContext):
        """Test getting a resource through a template."""
        manager = ResourceManager()

        def greet(name: str) -> str:
            return f"Hello, {name}!"

        manager.add_template(fn=greet, uri_template="greet://{name}", name="greeter")

        resource = await manager.get_resource(AnyUrl("greet://world"), make_context())
        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Hello, world!"

    @pytest.mark.anyio
    async def test_get_unknown_resource(self, make_context: MakeContext):
        """Test getting a non-existent resource."""
        manager = ResourceManager()
        with pytest.raises(ValueError, match="Unknown resource"):
            await manager.get_resource(AnyUrl("unknown://test"), make_context())

    def test_list_resources(self, temp_file: Path):
        """Test listing all resources."""
        manager = ResourceManager()
        resource1 = FileResource(
            uri=f"file://{temp_file}",
            name="test1",
            path=temp_file,
        )
        resource2 = FileResource(
            uri=f"file://{temp_file}2",
            name="test2",
            path=temp_file,
        )
        manager.add_resource(resource1)
        manager.add_resource(resource2)
        resources = manager.list_resources()
        assert len(resources) == 2
        assert resources == [resource1, resource2]


class TestResourceManagerMetadata:
    """Test ResourceManager Metadata"""

    def test_add_template_with_metadata(self):
        """Test that ResourceManager.add_template() accepts and passes meta parameter."""

        manager = ResourceManager()

        def get_item(id: str) -> str:  # pragma: no cover
            return f"Item {id}"

        metadata = {"source": "database", "cached": True}

        template = manager.add_template(
            fn=get_item,
            uri_template="resource://items/{id}",
            meta=metadata,
        )

        assert template.meta is not None
        assert template.meta == metadata
        assert template.meta["source"] == "database"
        assert template.meta["cached"] is True

    def test_add_template_without_metadata(self):
        """Test that ResourceManager.add_template() works without meta parameter."""

        manager = ResourceManager()

        def get_item(id: str) -> str:  # pragma: no cover
            return f"Item {id}"

        template = manager.add_template(
            fn=get_item,
            uri_template="resource://items/{id}",
        )

        assert template.meta is None

    def test_add_duplicate_template(self):
        """Test adding the same template twice returns the existing one."""
        manager = ResourceManager()

        def get_item(id: str) -> str:  # pragma: no cover
            return f"Item {id}"

        first = manager.add_template(fn=get_item, uri_template="resource://items/{id}")
        second = manager.add_template(fn=get_item, uri_template="resource://items/{id}")
        assert first is second
        assert len(manager.list_templates()) == 1

    def test_warn_on_duplicate_template(self, caplog: pytest.LogCaptureFixture):
        """Test warning on duplicate template."""
        manager = ResourceManager()

        def get_item(id: str) -> str:  # pragma: no cover
            return f"Item {id}"

        manager.add_template(fn=get_item, uri_template="resource://items/{id}")
        manager.add_template(fn=get_item, uri_template="resource://items/{id}")
        assert "Resource template already exists" in caplog.text

    def test_disable_warn_on_duplicate_template(self, caplog: pytest.LogCaptureFixture):
        """Test disabling warning on duplicate template."""
        manager = ResourceManager(warn_on_duplicate_resources=False)

        def get_item(id: str) -> str:  # pragma: no cover
            return f"Item {id}"

        manager.add_template(fn=get_item, uri_template="resource://items/{id}")
        manager.add_template(fn=get_item, uri_template="resource://items/{id}")
        assert "Resource template already exists" not in caplog.text
