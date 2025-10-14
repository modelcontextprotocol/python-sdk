import pytest
from pydantic import AnyUrl

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource, Resource
from mcp.types import Annotations


class TestResourceValidation:
    """Test base Resource validation."""

    def test_resource_uri_validation(self):
        """Test URI validation."""

        def dummy_func() -> str:
            return "data"

        # Valid URI
        resource = FunctionResource(
            uri=AnyUrl("http://example.com/data"),
            name="test",
            fn=dummy_func,
        )
        assert str(resource.uri) == "http://example.com/data"

        # Missing protocol
        with pytest.raises(ValueError, match="Input should be a valid URL"):
            FunctionResource(
                uri=AnyUrl("invalid"),
                name="test",
                fn=dummy_func,
            )

        # Missing host
        with pytest.raises(ValueError, match="Input should be a valid URL"):
            FunctionResource(
                uri=AnyUrl("http://"),
                name="test",
                fn=dummy_func,
            )

    def test_resource_name_from_uri(self):
        """Test name is extracted from URI if not provided."""

        def dummy_func() -> str:
            return "data"

        resource = FunctionResource(
            uri=AnyUrl("resource://my-resource"),
            fn=dummy_func,
        )
        assert resource.name == "resource://my-resource"

    def test_resource_name_validation(self):
        """Test name validation."""

        def dummy_func() -> str:
            return "data"

        # Must provide either name or URI
        with pytest.raises(ValueError, match="Either name or uri must be provided"):
            FunctionResource(
                fn=dummy_func,
            )

        # Explicit name takes precedence over URI
        resource = FunctionResource(
            uri=AnyUrl("resource://uri-name"),
            name="explicit-name",
            fn=dummy_func,
        )
        assert resource.name == "explicit-name"

    def test_resource_mime_type(self):
        """Test mime type handling."""

        def dummy_func() -> str:
            return "data"

        # Default mime type
        resource = FunctionResource(
            uri=AnyUrl("resource://test"),
            fn=dummy_func,
        )
        assert resource.mime_type == "text/plain"

        # Custom mime type
        resource = FunctionResource(
            uri=AnyUrl("resource://test"),
            fn=dummy_func,
            mime_type="application/json",
        )
        assert resource.mime_type == "application/json"

    @pytest.mark.anyio
    async def test_resource_read_abstract(self):
        """Test that Resource.read() is abstract."""

        class ConcreteResource(Resource):
            pass

        with pytest.raises(TypeError, match="abstract method"):
            ConcreteResource(uri=AnyUrl("test://test"), name="test")  # type: ignore


class TestResourceAnnotations:
    """Test annotations on resources."""

    def test_resource_with_annotations(self):
        """Test creating a resource with annotations."""

        def get_data() -> str:
            return "data"

        annotations = Annotations(audience=["user"], priority=0.8)

        resource = FunctionResource.from_function(fn=get_data, uri="resource://test", annotations=annotations)

        assert resource.annotations is not None
        assert resource.annotations.audience == ["user"]
        assert resource.annotations.priority == 0.8

    def test_resource_without_annotations(self):
        """Test that annotations are optional."""

        def get_data() -> str:
            return "data"

        resource = FunctionResource.from_function(fn=get_data, uri="resource://test")

        assert resource.annotations is None

    @pytest.mark.anyio
    async def test_resource_annotations_in_fastmcp(self):
        """Test resource annotations via FastMCP decorator."""

        mcp = FastMCP()

        @mcp.resource("resource://annotated", annotations=Annotations(audience=["assistant"], priority=0.5))
        def get_annotated() -> str:
            """An annotated resource."""
            return "annotated data"

        resources = await mcp.list_resources()
        assert len(resources) == 1
        assert resources[0].annotations is not None
        assert resources[0].annotations.audience == ["assistant"]
        assert resources[0].annotations.priority == 0.5

    @pytest.mark.anyio
    async def test_resource_annotations_with_both_audiences(self):
        """Test resource with both user and assistant audience."""

        mcp = FastMCP()

        @mcp.resource("resource://both", annotations=Annotations(audience=["user", "assistant"], priority=1.0))
        def get_both() -> str:
            return "for everyone"

        resources = await mcp.list_resources()
        assert resources[0].annotations is not None
        assert resources[0].annotations.audience == ["user", "assistant"]
        assert resources[0].annotations.priority == 1.0


class TestAnnotationsValidation:
    """Test validation of annotation values."""

    def test_priority_validation(self):
        """Test that priority is validated to be between 0.0 and 1.0."""

        # Valid priorities
        Annotations(priority=0.0)
        Annotations(priority=0.5)
        Annotations(priority=1.0)

        # Invalid priorities should raise validation error
        with pytest.raises(Exception):  # Pydantic validation error
            Annotations(priority=-0.1)

        with pytest.raises(Exception):
            Annotations(priority=1.1)

    def test_audience_validation(self):
        """Test that audience only accepts valid roles."""

        # Valid audiences
        Annotations(audience=["user"])
        Annotations(audience=["assistant"])
        Annotations(audience=["user", "assistant"])
        Annotations(audience=[])

        # Invalid roles should raise validation error
        with pytest.raises(Exception):  # Pydantic validation error
            Annotations(audience=["invalid_role"])  # type: ignore
