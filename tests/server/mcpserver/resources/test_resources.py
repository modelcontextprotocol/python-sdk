import pytest
from mcp_types import Annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import FunctionResource, Resource


class TestResourceValidation:
    def test_resource_uri_accepts_any_string(self):
        def dummy_func() -> str:  # pragma: no cover
            return "data"

        resource = FunctionResource(
            uri="http://example.com/data",
            name="test",
            fn=dummy_func,
        )
        assert resource.uri == "http://example.com/data"

        # Relative paths are valid per MCP spec
        resource = FunctionResource(
            uri="users/me",
            name="test",
            fn=dummy_func,
        )
        assert resource.uri == "users/me"

        resource = FunctionResource(
            uri="custom://resource",
            name="test",
            fn=dummy_func,
        )
        assert resource.uri == "custom://resource"

    def test_resource_name_from_uri(self):
        def dummy_func() -> str:  # pragma: no cover
            return "data"

        resource = FunctionResource(
            uri="resource://my-resource",
            fn=dummy_func,
        )
        assert resource.name == "resource://my-resource"

    def test_resource_name_validation(self):
        def dummy_func() -> str:  # pragma: no cover
            return "data"

        with pytest.raises(ValueError, match="Either name or uri must be provided"):
            FunctionResource(
                fn=dummy_func,
            )

        # Explicit name takes precedence over URI
        resource = FunctionResource(
            uri="resource://uri-name",
            name="explicit-name",
            fn=dummy_func,
        )
        assert resource.name == "explicit-name"

    def test_resource_mime_type(self):
        def dummy_func() -> str:  # pragma: no cover
            return "data"

        resource = FunctionResource(
            uri="resource://test",
            fn=dummy_func,
        )
        assert resource.mime_type == "text/plain"

        resource = FunctionResource(
            uri="resource://test",
            fn=dummy_func,
            mime_type="application/json",
        )
        assert resource.mime_type == "application/json"

        # RFC 2045 quoted parameter value (gh-1756)
        resource = FunctionResource(
            uri="resource://test",
            fn=dummy_func,
            mime_type='text/plain; charset="utf-8"',
        )
        assert resource.mime_type == 'text/plain; charset="utf-8"'

    @pytest.mark.anyio
    async def test_resource_read_abstract(self):
        class ConcreteResource(Resource):
            pass

        with pytest.raises(TypeError, match="abstract method"):
            ConcreteResource(uri="test://test", name="test")  # type: ignore


class TestResourceAnnotations:
    def test_resource_with_annotations(self):
        def get_data() -> str:  # pragma: no cover
            return "data"

        annotations = Annotations(audience=["user"], priority=0.8)

        resource = FunctionResource.from_function(fn=get_data, uri="resource://test", annotations=annotations)

        assert resource.annotations is not None
        assert resource.annotations.audience == ["user"]
        assert resource.annotations.priority == 0.8

    def test_resource_without_annotations(self):
        def get_data() -> str:  # pragma: no cover
            return "data"

        resource = FunctionResource.from_function(fn=get_data, uri="resource://test")

        assert resource.annotations is None

    @pytest.mark.anyio
    async def test_resource_annotations_in_mcpserver(self):
        mcp = MCPServer()

        @mcp.resource("resource://annotated", annotations=Annotations(audience=["assistant"], priority=0.5))
        def get_annotated() -> str:  # pragma: no cover
            """An annotated resource."""
            return "annotated data"

        resources = await mcp.list_resources()
        assert len(resources) == 1
        assert resources[0].annotations is not None
        assert resources[0].annotations.audience == ["assistant"]
        assert resources[0].annotations.priority == 0.5

    @pytest.mark.anyio
    async def test_resource_annotations_with_both_audiences(self):
        mcp = MCPServer()

        @mcp.resource("resource://both", annotations=Annotations(audience=["user", "assistant"], priority=1.0))
        def get_both() -> str:  # pragma: no cover
            return "for everyone"

        resources = await mcp.list_resources()
        assert resources[0].annotations is not None
        assert resources[0].annotations.audience == ["user", "assistant"]
        assert resources[0].annotations.priority == 1.0


class TestAnnotationsValidation:
    def test_priority_validation(self):
        Annotations(priority=0.0)
        Annotations(priority=0.5)
        Annotations(priority=1.0)

        with pytest.raises(Exception):  # Pydantic validation error
            Annotations(priority=-0.1)

        with pytest.raises(Exception):
            Annotations(priority=1.1)

    def test_audience_validation(self):
        Annotations(audience=["user"])
        Annotations(audience=["assistant"])
        Annotations(audience=["user", "assistant"])
        Annotations(audience=[])

        with pytest.raises(Exception):  # Pydantic validation error
            Annotations(audience=["invalid_role"])  # type: ignore


class TestResourceMetadata:
    def test_resource_with_metadata(self):
        def dummy_func() -> str:  # pragma: no cover
            return "data"

        metadata = {"version": "1.0", "category": "test"}

        resource = FunctionResource(
            uri="resource://test",
            name="test",
            fn=dummy_func,
            meta=metadata,
        )

        assert resource.meta is not None
        assert resource.meta == metadata
        assert resource.meta["version"] == "1.0"
        assert resource.meta["category"] == "test"

    def test_resource_without_metadata(self):
        def dummy_func() -> str:  # pragma: no cover
            return "data"

        resource = FunctionResource(
            uri="resource://test",
            name="test",
            fn=dummy_func,
        )

        assert resource.meta is None
