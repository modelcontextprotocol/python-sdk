import threading

import anyio
import anyio.from_thread
import pytest
from pydantic import BaseModel

from mcp.server.mcpserver.resources import FunctionResource


class TestFunctionResource:
    def test_function_resource_creation(self):
        def my_func() -> str:  # pragma: no cover
            return "test content"

        resource = FunctionResource(
            uri="fn://test",
            name="test",
            description="test function",
            fn=my_func,
        )
        assert str(resource.uri) == "fn://test"
        assert resource.name == "test"
        assert resource.description == "test function"
        assert resource.mime_type == "text/plain"  # default
        assert resource.fn == my_func

    @pytest.mark.anyio
    async def test_read_text(self):
        def get_data() -> str:
            return "Hello, world!"

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=get_data,
        )
        content = await resource.read()
        assert content == "Hello, world!"
        assert resource.mime_type == "text/plain"

    @pytest.mark.anyio
    async def test_read_binary(self):
        def get_data() -> bytes:
            return b"Hello, world!"

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=get_data,
        )
        content = await resource.read()
        assert content == b"Hello, world!"

    @pytest.mark.anyio
    async def test_json_conversion(self):
        def get_data() -> dict[str, str]:
            return {"key": "value"}

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=get_data,
        )
        content = await resource.read()
        assert isinstance(content, str)
        assert '"key": "value"' in content

    @pytest.mark.anyio
    async def test_error_handling(self):
        def failing_func() -> str:
            raise ValueError("Test error")

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=failing_func,
        )
        with pytest.raises(ValueError, match="Error reading resource function://test"):
            await resource.read()

    @pytest.mark.anyio
    async def test_basemodel_conversion(self):
        class MyModel(BaseModel):
            name: str

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=lambda: MyModel(name="test"),
        )
        content = await resource.read()
        assert content == '{\n  "name": "test"\n}'

    @pytest.mark.anyio
    async def test_custom_type_conversion(self):
        class CustomData:
            def __str__(self) -> str:
                return "custom data"

        def get_data() -> CustomData:
            return CustomData()

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=get_data,
        )
        content = await resource.read()
        assert isinstance(content, str)

    @pytest.mark.anyio
    async def test_async_read_text(self):
        async def get_data() -> str:
            return "Hello, world!"

        resource = FunctionResource(
            uri="function://test",
            name="test",
            fn=get_data,
        )
        content = await resource.read()
        assert content == "Hello, world!"
        assert resource.mime_type == "text/plain"

    @pytest.mark.anyio
    async def test_from_function(self):
        async def get_data() -> str:  # pragma: no cover
            """get_data returns a string"""
            return "Hello, world!"

        resource = FunctionResource.from_function(
            fn=get_data,
            uri="function://test",
            name="test",
        )

        assert resource.description == "get_data returns a string"
        assert resource.mime_type == "text/plain"
        assert resource.name == "test"
        assert resource.uri == "function://test"


class TestFunctionResourceMetadata:
    def test_from_function_with_metadata(self):
        def get_data() -> str:  # pragma: no cover
            return "test data"

        metadata = {"cache_ttl": 300, "tags": ["data", "readonly"]}

        resource = FunctionResource.from_function(
            fn=get_data,
            uri="resource://data",
            meta=metadata,
        )

        assert resource.meta is not None
        assert resource.meta == metadata
        assert resource.meta["cache_ttl"] == 300
        assert "data" in resource.meta["tags"]
        assert "readonly" in resource.meta["tags"]

    def test_from_function_without_metadata(self):
        def get_data() -> str:  # pragma: no cover
            return "test data"

        resource = FunctionResource.from_function(
            fn=get_data,
            uri="resource://data",
        )

        assert resource.meta is None


@pytest.mark.anyio
async def test_sync_fn_runs_in_worker_thread():
    main_thread = threading.get_ident()
    fn_thread: list[int] = []

    def blocking_fn() -> str:
        fn_thread.append(threading.get_ident())
        return "data"

    resource = FunctionResource(uri="resource://test", name="test", fn=blocking_fn)
    result = await resource.read()

    assert result == "data"
    assert fn_thread[0] != main_thread


@pytest.mark.anyio
async def test_sync_fn_does_not_block_event_loop():
    # On regression (sync runs inline), anyio.from_thread.run_sync raises RuntimeError (no worker-thread context).
    handler_entered = anyio.Event()
    release = threading.Event()

    def blocking_fn() -> str:
        anyio.from_thread.run_sync(handler_entered.set)
        release.wait()
        return "done"

    resource = FunctionResource(uri="resource://test", name="test", fn=blocking_fn)
    result: list[str | bytes] = []

    async def run() -> None:
        result.append(await resource.read())

    with anyio.fail_after(5):
        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
            await handler_entered.wait()
            release.set()

    assert result == ["done"]
