import json
import threading
from typing import Any

import pytest
from mcp_types import Annotations
from pydantic import BaseModel

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.server.mcpserver.resources import FunctionResource, ResourceTemplate
from mcp.server.mcpserver.resources.templates import (
    DEFAULT_RESOURCE_SECURITY,
    ResourceSecurity,
    ResourceSecurityError,
)


def _make(uri_template: str, security: ResourceSecurity = DEFAULT_RESOURCE_SECURITY) -> ResourceTemplate:
    def handler(**kwargs: Any) -> str:
        raise NotImplementedError  # these tests only exercise matches()

    return ResourceTemplate.from_function(fn=handler, uri_template=uri_template, security=security)


def test_matches_rfc6570_reserved_expansion():
    # {+path} allows / — the feature the old regex implementation couldn't support
    t = _make("file://docs/{+path}")
    assert t.matches("file://docs/src/main.py") == {"path": "src/main.py"}


def test_matches_rejects_encoded_slash_traversal():
    # %2F decodes to '/' in UriTemplate.match(); the traversal check then rejects the '..' components.
    t = _make("file://docs/{name}")
    with pytest.raises(ResourceSecurityError, match="'name'"):
        t.matches("file://docs/..%2F..%2Fetc%2Fpasswd")


def test_matches_rejects_path_traversal_by_default():
    t = _make("file://docs/{name}")
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs/..")


def test_matches_rejects_path_traversal_in_reserved_var():
    # Even {+path} gets the traversal check — it's semantic, not structural
    t = _make("file://docs/{+path}")
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs/../../etc/passwd")


def test_matches_rejects_absolute_path():
    t = _make("file://docs/{+path}")
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs//etc/passwd")


def test_matches_allows_dotdot_as_substring():
    # .. is only dangerous as a path component
    t = _make("git://refs/{range}")
    assert t.matches("git://refs/v1.0..v2.0") == {"range": "v1.0..v2.0"}


def test_matches_exempt_params_skip_security():
    policy = ResourceSecurity(exempt_params={"range"})
    t = _make("git://diff/{+range}", security=policy)
    assert t.matches("git://diff/../foo") == {"range": "../foo"}


def test_matches_disabled_policy_allows_traversal():
    policy = ResourceSecurity(reject_path_traversal=False, reject_absolute_paths=False)
    t = _make("file://docs/{name}", security=policy)
    assert t.matches("file://docs/..") == {"name": ".."}


def test_matches_rejects_null_byte_by_default():
    # %00 decodes to \x00, which defeats string comparisons ("..\x00" != "..") and can truncate in C extensions.
    t = _make("file://docs/{name}")
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs/key%00.txt")
    # Null byte also defeats the traversal check's component comparison
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs/..%00%2Fsecret")


def test_matches_null_byte_check_can_be_disabled():
    policy = ResourceSecurity(reject_null_bytes=False)
    t = _make("file://docs/{name}", security=policy)
    assert t.matches("file://docs/key%00.txt") == {"name": "key\x00.txt"}


def test_security_rejection_does_not_fall_through_to_next_template():
    # A strict template's rejection must halt iteration, not fall through to a later permissive template:
    # matches() once returned None for both "no match" and "security failed", making registration order critical.
    strict = _make("file://docs/{name}")
    lax = _make(
        "file://docs/{+path}",
        security=ResourceSecurity(exempt_params={"path"}),
    )
    uri = "file://docs/..%2Fsecrets"
    with pytest.raises(ResourceSecurityError) as exc:
        strict.matches(uri)
    assert exc.value.param == "name"
    # Prove the lax template WOULD have accepted the URI — the raise above is what prevents fall-through.
    assert lax.matches(uri) == {"path": "../secrets"}


def test_matches_explode_checks_each_segment():
    t = _make("api{/parts*}")
    assert t.matches("api/a/b/c") == {"parts": ["a", "b", "c"]}
    # Any segment with traversal rejects the whole match
    with pytest.raises(ResourceSecurityError):
        t.matches("api/a/../c")


def test_matches_encoded_backslash_caught_by_traversal_check():
    # %5C decodes to '\'; the traversal check normalizes '\' to '/' and catches the '..' components.
    t = _make("file://docs/{name}")
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs/..%5C..%5Csecret")


def test_matches_encoded_dots_caught_by_traversal_check():
    t = _make("file://docs/{name}")
    with pytest.raises(ResourceSecurityError):
        t.matches("file://docs/%2E%2E")


def test_matches_mixed_encoded_and_literal_slash():
    # The literal '/' stops the simple-var regex, so the URI doesn't match the template at all.
    t = _make("file://docs/{name}")
    assert t.matches("file://docs/..%2F../etc") is None


def test_matches_encoded_slash_without_traversal_allowed():
    # ResourceSecurity only blocks '..' and absolute paths; a decoded '/' alone is allowed.
    # Handlers that need single-segment values must use safe_join or validate explicitly.
    t = _make("file://docs/{name}")
    assert t.matches("file://docs/sub%2Ffile.txt") == {"name": "sub/file.txt"}


def test_matches_escapes_template_literals():
    # Regression: old impl treated . as regex wildcard
    t = _make("data://v1.0/{id}")
    assert t.matches("data://v1.0/42") == {"id": "42"}
    assert t.matches("data://v1X0/42") is None


class TestResourceTemplate:
    def test_template_creation(self):
        def my_func(key: str, value: int) -> dict[str, Any]:
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )
        assert template.uri_template == "test://{key}/{value}"
        assert template.name == "test"
        assert template.mime_type == "text/plain"  # default
        assert template.fn(key="test", value=42) == my_func(key="test", value=42)

    def test_template_matches(self):
        def my_func(key: str, value: int) -> dict[str, Any]:  # pragma: no cover
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )

        params = template.matches("test://foo/123")
        assert params == {"key": "foo", "value": "123"}

        assert template.matches("test://foo") is None
        assert template.matches("other://foo/123") is None

    @pytest.mark.anyio
    async def test_create_resource(self):
        def my_func(key: str, value: int) -> dict[str, Any]:
            return {"key": key, "value": value}

        template = ResourceTemplate.from_function(
            fn=my_func,
            uri_template="test://{key}/{value}",
            name="test",
        )

        resource = await template.create_resource(
            "test://foo/123",
            {"key": "foo", "value": 123},
            Context(),
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert isinstance(content, str)
        data = json.loads(content)
        assert data == {"key": "foo", "value": 123}

    @pytest.mark.anyio
    async def test_template_error(self):
        def failing_func(x: str) -> str:
            raise ValueError("Test error")

        template = ResourceTemplate.from_function(
            fn=failing_func,
            uri_template="fail://{x}",
            name="fail",
        )

        with pytest.raises(ResourceError, match="Error creating resource from template"):
            await template.create_resource("fail://test", {"x": "test"}, Context())

    @pytest.mark.anyio
    async def test_async_text_resource(self):
        async def greet(name: str) -> str:
            return f"Hello, {name}!"

        template = ResourceTemplate.from_function(
            fn=greet,
            uri_template="greet://{name}",
            name="greeter",
        )

        resource = await template.create_resource(
            "greet://world",
            {"name": "world"},
            Context(),
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == "Hello, world!"

    @pytest.mark.anyio
    async def test_async_binary_resource(self):
        async def get_bytes(value: str) -> bytes:
            return value.encode()

        template = ResourceTemplate.from_function(
            fn=get_bytes,
            uri_template="bytes://{value}",
            name="bytes",
        )

        resource = await template.create_resource(
            "bytes://test",
            {"value": "test"},
            Context(),
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == b"test"

    @pytest.mark.anyio
    async def test_basemodel_conversion(self):
        class MyModel(BaseModel):
            key: str
            value: int

        def get_data(key: str, value: int) -> MyModel:
            return MyModel(key=key, value=value)

        template = ResourceTemplate.from_function(
            fn=get_data,
            uri_template="test://{key}/{value}",
            name="test",
        )

        resource = await template.create_resource(
            "test://foo/123",
            {"key": "foo", "value": 123},
            Context(),
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert isinstance(content, str)
        data = json.loads(content)
        assert data == {"key": "foo", "value": 123}

    @pytest.mark.anyio
    async def test_custom_type_conversion(self):
        class CustomData:
            def __init__(self, value: str):
                self.value = value

            def __str__(self) -> str:
                return self.value

        def get_data(value: str) -> CustomData:
            return CustomData(value)

        template = ResourceTemplate.from_function(
            fn=get_data,
            uri_template="test://{value}",
            name="test",
        )

        resource = await template.create_resource(
            "test://hello",
            {"value": "hello"},
            Context(),
        )

        assert isinstance(resource, FunctionResource)
        content = await resource.read()
        assert content == '"hello"'


class TestResourceTemplateAnnotations:
    def test_template_with_annotations(self):
        def get_user_data(user_id: str) -> str:  # pragma: no cover
            return f"User {user_id}"

        annotations = Annotations(priority=0.9)

        template = ResourceTemplate.from_function(
            fn=get_user_data, uri_template="resource://users/{user_id}", annotations=annotations
        )

        assert template.annotations is not None
        assert template.annotations.priority == 0.9

    def test_template_without_annotations(self):
        def get_user_data(user_id: str) -> str:  # pragma: no cover
            return f"User {user_id}"

        template = ResourceTemplate.from_function(fn=get_user_data, uri_template="resource://users/{user_id}")

        assert template.annotations is None

    @pytest.mark.anyio
    async def test_template_annotations_in_mcpserver(self):
        mcp = MCPServer()

        @mcp.resource("resource://dynamic/{id}", annotations=Annotations(audience=["user"], priority=0.7))
        def get_dynamic(id: str) -> str:  # pragma: no cover
            """A dynamic annotated resource."""
            return f"Data for {id}"

        templates = await mcp.list_resource_templates()
        assert len(templates) == 1
        assert templates[0].annotations is not None
        assert templates[0].annotations.audience == ["user"]
        assert templates[0].annotations.priority == 0.7

    @pytest.mark.anyio
    async def test_template_created_resources_inherit_annotations(self):
        def get_item(item_id: str) -> str:
            return f"Item {item_id}"

        annotations = Annotations(priority=0.6)

        template = ResourceTemplate.from_function(
            fn=get_item, uri_template="resource://items/{item_id}", annotations=annotations
        )

        resource = await template.create_resource("resource://items/123", {"item_id": "123"}, Context())

        assert resource.annotations is not None
        assert resource.annotations.priority == 0.6

        content = await resource.read()
        assert content == "Item 123"


class TestResourceTemplateMetadata:
    def test_template_from_function_with_metadata(self):
        def get_user(user_id: str) -> str:  # pragma: no cover
            return f"User {user_id}"

        metadata = {"requires_auth": True, "rate_limit": 100}

        template = ResourceTemplate.from_function(
            fn=get_user,
            uri_template="resource://users/{user_id}",
            meta=metadata,
        )

        assert template.meta is not None
        assert template.meta == metadata
        assert template.meta["requires_auth"] is True
        assert template.meta["rate_limit"] == 100

    @pytest.mark.anyio
    async def test_template_created_resources_inherit_metadata(self):
        def get_item(item_id: str) -> str:
            return f"Item {item_id}"

        metadata = {"category": "inventory", "cacheable": True}

        template = ResourceTemplate.from_function(
            fn=get_item,
            uri_template="resource://items/{item_id}",
            meta=metadata,
        )

        resource = await template.create_resource("resource://items/123", {"item_id": "123"}, Context())

        assert resource.meta is not None
        assert resource.meta == metadata
        assert resource.meta["category"] == "inventory"
        assert resource.meta["cacheable"] is True


@pytest.mark.anyio
async def test_sync_fn_runs_in_worker_thread():
    main_thread = threading.get_ident()
    fn_thread: list[int] = []

    def blocking_fn(name: str) -> str:
        fn_thread.append(threading.get_ident())
        return f"hello {name}"

    template = ResourceTemplate.from_function(fn=blocking_fn, uri_template="test://{name}")
    resource = await template.create_resource("test://world", {"name": "world"}, Context())

    assert isinstance(resource, FunctionResource)
    assert await resource.read() == "hello world"
    assert fn_thread[0] != main_thread
