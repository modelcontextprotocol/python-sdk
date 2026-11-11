import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import AnyUrl

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceNotFoundError
from mcp.server.mcpserver.resources import (
    FileResource,
    FunctionResource,
    Resource,
    ResourceManager,
    ResourceTemplate,
    TextResource,
)


class _CountingTuple(tuple[Resource, ...]):
    """A tuple that records how many times it is iterated."""

    iterations = 0

    def __iter__(self) -> Iterator[Resource]:
        self.iterations += 1
        return super().__iter__()


@pytest.fixture()
def temp_file(tmp_path: Path):
    """Create a temporary file for testing.

    File is automatically cleaned up after the test if it still exists.
    """
    tmp_file = tmp_path / "file"
    tmp_file.touch()
    yield tmp_file


def test_init_with_resources(temp_file: Path, caplog: pytest.LogCaptureFixture):
    resource = FileResource(uri=f"file://{temp_file}", name="test", path=temp_file)
    manager = ResourceManager(resources=[resource])
    assert manager.list_resources() == [resource]

    duplicate_resource = FileResource(uri=f"file://{temp_file}", name="duplicate", path=temp_file)

    with caplog.at_level(logging.WARNING):
        manager = ResourceManager(True, resources=[resource, duplicate_resource])

    assert "Resource already exists" in caplog.text
    assert manager.list_resources() == [resource]


def test_add_resource(temp_file: Path):
    """Test adding a resource."""
    manager = ResourceManager()
    resource = FileResource(uri=f"file://{temp_file}", name="test", path=temp_file)
    added = manager.add_resource(resource)
    assert added == resource
    assert manager.list_resources() == [resource]


def test_add_duplicate_resource(temp_file: Path):
    """Test adding the same resource twice."""
    manager = ResourceManager()
    resource = FileResource(uri=f"file://{temp_file}", name="test", path=temp_file)
    first = manager.add_resource(resource)
    second = manager.add_resource(resource)
    assert first == second
    assert manager.list_resources() == [resource]


def test_warn_on_duplicate_resources(temp_file: Path, caplog: pytest.LogCaptureFixture):
    """Test warning on duplicate resources."""
    manager = ResourceManager()
    resource = FileResource(uri=f"file://{temp_file}", name="test", path=temp_file)
    manager.add_resource(resource)
    manager.add_resource(resource)
    assert "Resource already exists" in caplog.text


def test_disable_warn_on_duplicate_resources(temp_file: Path, caplog: pytest.LogCaptureFixture):
    """Test disabling warning on duplicate resources."""
    manager = ResourceManager(warn_on_duplicate_resources=False)
    resource = FileResource(uri=f"file://{temp_file}", name="test", path=temp_file)
    manager.add_resource(resource)
    manager.add_resource(resource)
    assert "Resource already exists" not in caplog.text


@pytest.mark.anyio
async def test_get_resource(temp_file: Path):
    """Test getting a resource by URI."""
    manager = ResourceManager()
    resource = FileResource(uri=f"file://{temp_file}", name="test", path=temp_file)
    manager.add_resource(resource)
    retrieved = await manager.get_resource(resource.uri, Context())
    assert retrieved == resource


@pytest.mark.anyio
async def test_get_resource_from_template():
    """Test getting a resource through a template."""
    manager = ResourceManager()

    def greet(name: str) -> str:
        return f"Hello, {name}!"

    template = ResourceTemplate.from_function(fn=greet, uri_template="greet://{name}", name="greeter")
    manager._templates[template.uri_template] = template

    resource = await manager.get_resource(AnyUrl("greet://world"), Context())
    assert isinstance(resource, FunctionResource)
    content = await resource.read()
    assert content == "Hello, world!"


@pytest.mark.anyio
async def test_get_unknown_resource():
    """Test getting a non-existent resource."""
    manager = ResourceManager()
    with pytest.raises(ResourceNotFoundError, match="Unknown resource"):
        await manager.get_resource(AnyUrl("unknown://test"), Context())


def test_list_resources(temp_file: Path):
    """Test listing all resources."""
    manager = ResourceManager()
    resource1 = FileResource(uri=f"file://{temp_file}", name="test1", path=temp_file)
    resource2 = FileResource(uri=f"file://{temp_file}2", name="test2", path=temp_file)

    manager.add_resource(resource1)
    manager.add_resource(resource2)

    resources = manager.list_resources()
    assert len(resources) == 2
    assert resources == [resource1, resource2]


@pytest.mark.anyio
async def test_a_provider_that_keeps_returning_the_same_tuple_is_scanned_once():
    """SDK-defined: lookups reuse the URI index while a provider returns the same immutable tuple."""
    first = TextResource(uri="dyn://first", name="first", text="1")
    second = TextResource(uri="dyn://second", name="second", text="2")
    served = _CountingTuple((first, second))
    manager = ResourceManager()
    manager.add_resource_provider(lambda: served)

    assert await manager.get_resource("dyn://second", Context()) is second
    assert await manager.get_resource("dyn://first", Context()) is first
    assert manager.list_resources() == [first, second]
    assert served.iterations == 1


@pytest.mark.anyio
async def test_a_provider_that_returns_a_new_tuple_is_indexed_again():
    """SDK-defined: replacing the tuple a provider returns replaces what lookups find."""
    old = TextResource(uri="dyn://old", name="old", text="old")
    new = TextResource(uri="dyn://new", name="new", text="new")
    current: list[tuple[Resource, ...]] = [(old,)]
    manager = ResourceManager()
    manager.add_resource_provider(lambda: current[0])

    assert await manager.get_resource("dyn://old", Context()) is old
    current[0] = (new,)
    assert await manager.get_resource("dyn://new", Context()) is new
    with pytest.raises(ResourceNotFoundError):
        await manager.get_resource("dyn://old", Context())


@pytest.mark.anyio
async def test_a_list_from_a_provider_is_rescanned_so_changes_made_in_place_are_seen():
    """SDK-defined: only tuples are indexed, because a list may be mutated after it is returned."""
    old = TextResource(uri="dyn://old", name="old", text="old")
    new = TextResource(uri="dyn://new", name="new", text="new")
    served: list[Resource] = [old]
    manager = ResourceManager()
    manager.add_resource_provider(lambda: served)

    assert await manager.get_resource("dyn://old", Context()) is old
    served.append(new)
    assert await manager.get_resource("dyn://new", Context()) is new
    assert manager.list_resources() == [old, new]


def get_item(id: str) -> str: ...


def test_add_template_with_metadata():
    """Test that ResourceManager.add_template() accepts and passes meta parameter."""
    manager = ResourceManager()
    metadata = {"source": "database", "cached": True}
    template = manager.add_template(fn=get_item, uri_template="resource://items/{id}", meta=metadata)

    assert template.meta is not None
    assert template.meta == metadata
    assert template.meta["source"] == "database"
    assert template.meta["cached"] is True


def test_add_template_without_metadata():
    """Test that ResourceManager.add_template() works without meta parameter."""
    manager = ResourceManager()
    template = manager.add_template(fn=get_item, uri_template="resource://items/{id}")
    assert template.meta is None
