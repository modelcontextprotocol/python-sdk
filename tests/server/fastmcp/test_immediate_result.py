"""Test immediate_result functionality in FastMCP."""

import anyio
import pytest

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool, ToolManager
from mcp.shared.exceptions import McpError
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import INVALID_PARAMS, ContentBlock, ErrorData, TextContent


class TestImmediateResultValidation:
    """Test validation of immediate_result parameter during tool registration."""

    def test_immediate_result_with_sync_only_tool_fails(self):
        """Test that immediate_result fails with sync-only tools."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        def sync_tool() -> str:
            """A sync tool."""
            return "sync"

        manager = ToolManager()

        # Should raise ValueError when immediate_result is used with sync-only tool
        with pytest.raises(ValueError, match="immediate_result can only be used with async-compatible tools"):
            manager.add_tool(sync_tool, invocation_modes=["sync"], immediate_result=immediate_fn)

    def test_immediate_result_with_async_tool_succeeds(self):
        """Test that immediate_result succeeds with async-compatible tools."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            """An async tool."""
            return "async"

        manager = ToolManager()

        # Should succeed with async-compatible tool
        tool = manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=immediate_fn)
        assert tool.immediate_result == immediate_fn
        assert tool.invocation_modes == ["async"]

    def test_immediate_result_with_hybrid_tool_succeeds(self):
        """Test that immediate_result succeeds with hybrid sync/async tools."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        def hybrid_tool() -> str:
            """A hybrid tool."""
            return "hybrid"

        manager = ToolManager()

        # Should succeed with hybrid tool
        tool = manager.add_tool(hybrid_tool, invocation_modes=["sync", "async"], immediate_result=immediate_fn)
        assert tool.immediate_result == immediate_fn
        assert tool.invocation_modes == ["sync", "async"]

    def test_immediate_result_non_async_callable_fails(self):
        """Test that non-async immediate_result functions fail validation."""

        def sync_immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        # Should raise ValueError for non-async immediate_result function
        with pytest.raises(ValueError, match="immediate_result must be an async callable"):
            manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=sync_immediate_fn)  # type: ignore

    def test_immediate_result_non_callable_fails(self):
        """Test that non-callable immediate_result fails validation."""

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        # Should raise ValueError for non-callable immediate_result
        with pytest.raises(ValueError, match="immediate_result must be an async callable"):
            manager.add_tool(async_tool, invocation_modes=["async"], immediate_result="not_callable")  # type: ignore

    def test_tool_from_function_immediate_result_validation(self):
        """Test Tool.from_function validates immediate_result correctly."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        def sync_tool() -> str:
            return "sync"

        # Should fail with sync-only tool
        with pytest.raises(ValueError, match="immediate_result can only be used with async-compatible tools"):
            Tool.from_function(sync_tool, invocation_modes=["sync"], immediate_result=immediate_fn)

        # Should succeed with async tool
        async def async_tool() -> str:
            return "async"

        tool = Tool.from_function(async_tool, invocation_modes=["async"], immediate_result=immediate_fn)
        assert tool.immediate_result == immediate_fn


class TestImmediateResultIntegration:
    """Test integration of immediate_result with async operations and polling."""

    @pytest.mark.anyio
    async def test_fastmcp_tool_decorator_with_immediate_result(self):
        """Test FastMCP tool decorator with immediate_result parameter."""

        mcp = FastMCP()

        async def immediate_feedback(operation: str) -> list[ContentBlock]:
            return [TextContent(type="text", text=f"🚀 Starting {operation}...")]

        @mcp.tool(invocation_modes=["async"], immediate_result=immediate_feedback)
        async def long_running_task(operation: str) -> str:
            """Perform a long-running task with immediate feedback."""
            await anyio.sleep(0.1)  # Simulate work
            return f"Task '{operation}' completed!"

        # Test with "next" protocol version to see async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            assert tools.tools[0].name == "long_running_task"
            assert tools.tools[0].invocationMode == "async"

        # Test that the tool has immediate_result in the internal representation
        internal_tool = mcp._tool_manager.get_tool("long_running_task")
        assert internal_tool is not None
        assert internal_tool.immediate_result == immediate_feedback

    @pytest.mark.anyio
    async def test_tool_without_immediate_result_backward_compatibility(self):
        """Test that async tools without immediate_result work unchanged."""

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"])
        async def simple_async_tool(message: str) -> str:
            """A simple async tool without immediate result."""
            await anyio.sleep(0.1)
            return f"Processed: {message}"

        # Test with "next" protocol version to see async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            assert tools.tools[0].name == "simple_async_tool"
            assert tools.tools[0].invocationMode == "async"

        # Test that the tool has no immediate_result
        internal_tool = mcp._tool_manager.get_tool("simple_async_tool")
        assert internal_tool is not None
        assert internal_tool.immediate_result is None

    @pytest.mark.anyio
    async def test_sync_tool_unchanged_behavior(self):
        """Test that sync tools continue to work without modification."""

        mcp = FastMCP()

        @mcp.tool()
        def sync_tool(message: str) -> str:
            """A simple sync tool."""
            return f"Processed: {message}"

        # Test with old client (sync tools should be visible)
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            assert tools.tools[0].name == "sync_tool"
            assert tools.tools[0].invocationMode is None  # Old clients don't see invocationMode

        # Test with "next" protocol version
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1
            assert tools.tools[0].name == "sync_tool"
            assert tools.tools[0].invocationMode == "sync"  # New clients see invocationMode

        # Test that the tool has no immediate_result
        internal_tool = mcp._tool_manager.get_tool("sync_tool")
        assert internal_tool is not None
        assert internal_tool.immediate_result is None
        assert internal_tool.invocation_modes == ["sync"]

    @pytest.mark.anyio
    async def test_multiple_tools_with_mixed_immediate_result(self):
        """Test multiple tools with mixed immediate_result configurations."""

        mcp = FastMCP()

        async def immediate_feedback(message: str) -> list[ContentBlock]:
            return [TextContent(type="text", text=f"Processing: {message}")]

        @mcp.tool(invocation_modes=["async"], immediate_result=immediate_feedback)
        async def tool_with_immediate(message: str) -> str:
            return f"Done: {message}"

        @mcp.tool(invocation_modes=["async"])
        async def tool_without_immediate(message: str) -> str:
            return f"Done: {message}"

        @mcp.tool()
        def sync_tool(message: str) -> str:
            return f"Done: {message}"

        # Test with old client (only sync tools visible)
        async with create_connected_server_and_client_session(mcp._mcp_server) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 1  # Only sync tool visible
            assert tools.tools[0].name == "sync_tool"

        # Test with "next" protocol version (all tools visible)
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 3

            tool_names = {tool.name for tool in tools.tools}
            assert tool_names == {"tool_with_immediate", "tool_without_immediate", "sync_tool"}

        # Test internal representations
        tool_with = mcp._tool_manager.get_tool("tool_with_immediate")
        tool_without = mcp._tool_manager.get_tool("tool_without_immediate")
        sync_tool_obj = mcp._tool_manager.get_tool("sync_tool")

        assert tool_with is not None and tool_with.immediate_result == immediate_feedback
        assert tool_without is not None and tool_without.immediate_result is None
        assert sync_tool_obj is not None and sync_tool_obj.immediate_result is None


class TestImmediateResultErrorHandling:
    """Test error handling for immediate_result functionality."""

    def test_registration_error_messages(self):
        """Test that registration errors have clear messages."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        def sync_tool() -> str:
            return "sync"

        manager = ToolManager()

        # Test error message for sync-only tool
        with pytest.raises(ValueError) as exc_info:
            manager.add_tool(sync_tool, invocation_modes=["sync"], immediate_result=immediate_fn)

        error_msg = str(exc_info.value)
        assert "immediate_result can only be used with async-compatible tools" in error_msg
        assert "Add 'async' to invocation_modes" in error_msg

    def test_fastmcp_decorator_sync_tool_validation(self):
        """Test that FastMCP decorator prevents sync tools from using immediate_result."""

        mcp = FastMCP()

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        # Should raise ValueError when decorating sync tool with immediate_result
        with pytest.raises(ValueError, match="immediate_result can only be used with async-compatible tools"):

            @mcp.tool(invocation_modes=["sync"], immediate_result=immediate_fn)
            def sync_tool_with_immediate() -> str:
                return "sync"

    def test_default_sync_tool_validation(self):
        """Test that default sync tools (no invocation_modes specified) cannot use immediate_result."""

        mcp = FastMCP()

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        # Should raise ValueError when decorating default sync tool with immediate_result
        with pytest.raises(ValueError, match="immediate_result can only be used with async-compatible tools"):

            @mcp.tool(immediate_result=immediate_fn)
            def default_sync_tool() -> str:
                return "sync"

    def test_non_async_callable_error_message(self):
        """Test error message for non-async immediate_result function."""

        def sync_immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        with pytest.raises(ValueError) as exc_info:
            manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=sync_immediate_fn)  # type: ignore

        error_msg = str(exc_info.value)
        assert "immediate_result must be an async callable" in error_msg

    def test_tool_manager_duplicate_tool_handling_with_immediate_result(self):
        """Test duplicate tool handling when immediate_result is involved."""

        async def immediate_fn1() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate1")]

        async def immediate_fn2() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate2")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        # Add first tool with immediate_result
        tool1 = manager.add_tool(
            async_tool, name="test_tool", invocation_modes=["async"], immediate_result=immediate_fn1
        )

        # Add duplicate tool with different immediate_result (should return existing)
        tool2 = manager.add_tool(
            async_tool, name="test_tool", invocation_modes=["async"], immediate_result=immediate_fn2
        )

        # Should return the same tool (first one registered)
        assert tool1 is tool2
        assert tool1.immediate_result == immediate_fn1


class TestImmediateResultPerformance:
    """Test performance aspects of immediate_result functionality."""

    def test_no_performance_impact_without_immediate_result(self):
        """Test that tools without immediate_result have no performance impact."""

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        # Add tool without immediate_result
        tool = manager.add_tool(async_tool, invocation_modes=["async"])

        # Verify no immediate_result overhead
        assert tool.immediate_result is None
        assert "async" in tool.invocation_modes

    @pytest.mark.anyio
    async def test_immediate_result_function_isolation(self):
        """Test that immediate_result functions are isolated from main tool execution."""

        execution_order: list[str] = []

        async def immediate_fn(message: str) -> list[ContentBlock]:
            execution_order.append("immediate")
            return [TextContent(type="text", text=f"Processing: {message}")]

        async def async_tool(message: str) -> str:
            execution_order.append("main")
            await anyio.sleep(0.1)
            return f"Completed: {message}"

        manager = ToolManager()
        tool = manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=immediate_fn)

        # Test that immediate function can be called independently
        await immediate_fn("test")
        assert execution_order == ["immediate"]

        # Reset and test main function
        execution_order.clear()
        await tool.run({"message": "test"})
        assert execution_order == ["main"]


class TestImmediateResultRuntimeErrors:
    """Test runtime error handling when immediate_result functions raise exceptions."""

    @pytest.mark.anyio
    async def test_immediate_result_registration_and_storage(self):
        """Test that immediate_result functions are properly registered, stored, and executed."""

        async def working_immediate_fn(message: str) -> list[ContentBlock]:
            return [TextContent(type="text", text=f"Processing: {message}")]

        async def async_tool(message: str) -> str:
            await anyio.sleep(0.1)
            return f"Completed: {message}"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=working_immediate_fn)
        async def tool_with_working_immediate(message: str) -> str:
            """Tool with working immediate result."""
            return await async_tool(message)

        # Verify the tool was registered with immediate_result
        internal_tool = mcp._tool_manager.get_tool("tool_with_working_immediate")
        assert internal_tool is not None
        assert internal_tool.immediate_result == working_immediate_fn

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # Call the tool - should return operation token
            result = await client.call_tool("tool_with_working_immediate", {"message": "test"})

            # Should get operation token for async call
            assert result.operation is not None
            token = result.operation.token

            # The immediate result should be in the initial response content
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            assert content.text == "Processing: test"

            # Poll for completion to verify main tool execution
            while True:
                status = await client.get_operation_status(token)
                if status.status == "completed":
                    final_result = await client.get_operation_result(token)
                    assert not final_result.result.isError
                    assert len(final_result.result.content) == 1
                    final_content = final_result.result.content[0]
                    assert final_content.type == "text"
                    assert final_content.text == "Completed: test"
                    break
                elif status.status == "failed":
                    pytest.fail(f"Tool execution failed: {status}")
                await anyio.sleep(0.01)

    @pytest.mark.anyio
    async def test_immediate_result_exception_handling(self):
        """Test that exceptions in immediate_result are properly handled during tool execution."""

        async def failing_immediate_fn(message: str) -> list[ContentBlock]:
            raise ValueError(f"Immediate result failed for: {message}")

        async def async_tool(message: str) -> str:
            await anyio.sleep(0.1)
            return f"Completed: {message}"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=failing_immediate_fn)
        async def tool_with_failing_immediate(message: str) -> str:
            """Tool with failing immediate result."""
            return await async_tool(message)

        # Verify the tool was registered with the failing immediate_result
        internal_tool = mcp._tool_manager.get_tool("tool_with_failing_immediate")
        assert internal_tool is not None
        assert internal_tool.immediate_result == failing_immediate_fn

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # The call should return an error result due to immediate_result exception
            result = await client.call_tool("tool_with_failing_immediate", {"message": "test"})

            # Verify error result
            assert result.isError is True
            assert result.operation is None  # No operation created due to immediate_result failure
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            assert "Immediate result execution error" in content.text
            assert "Immediate result failed for: test" in content.text

    @pytest.mark.anyio
    async def test_immediate_result_invalid_return_type_error(self):
        """Test that immediate_result returning invalid type is handled properly."""

        async def invalid_return_immediate_fn(message: str) -> str:  # Wrong return type
            return f"Invalid return: {message}"  # Should return list[ContentBlock]

        async def async_tool(message: str) -> str:
            return f"Completed: {message}"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=invalid_return_immediate_fn)  # type: ignore
        async def tool_with_invalid_immediate(message: str) -> str:
            """Tool with invalid immediate result return type."""
            return await async_tool(message)

        # Verify the tool was registered (type checking is not enforced at runtime)
        internal_tool = mcp._tool_manager.get_tool("tool_with_invalid_immediate")
        assert internal_tool is not None
        assert internal_tool.immediate_result == invalid_return_immediate_fn

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # The call should return an error result due to invalid return type
            result = await client.call_tool("tool_with_invalid_immediate", {"message": "test"})

            # Verify error result
            assert result.isError is True
            assert result.operation is None  # No operation created due to immediate_result failure
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            assert "Immediate result execution error" in content.text
            assert "immediate_result must return list[ContentBlock]" in content.text

    @pytest.mark.anyio
    async def test_immediate_result_async_exception_handling(self):
        """Test that async exceptions in immediate_result are properly handled."""

        async def async_failing_immediate_fn(operation: str) -> list[ContentBlock]:
            await anyio.sleep(0.01)  # Make it truly async
            raise RuntimeError(f"Async immediate failure: {operation}")

        async def async_tool(operation: str) -> str:
            await anyio.sleep(0.1)
            return f"Operation {operation} completed"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=async_failing_immediate_fn)
        async def tool_with_async_failing_immediate(operation: str) -> str:
            """Tool with async failing immediate result."""
            return await async_tool(operation)

        # Verify the tool was registered
        internal_tool = mcp._tool_manager.get_tool("tool_with_async_failing_immediate")
        assert internal_tool is not None
        assert internal_tool.immediate_result == async_failing_immediate_fn

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # The call should return an error result due to immediate_result exception
            result = await client.call_tool("tool_with_async_failing_immediate", {"operation": "test_op"})

            # Verify error result
            assert result.isError is True
            assert result.operation is None  # No operation created due to immediate_result failure
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            assert "Immediate result execution error" in content.text
            assert "Async immediate failure: test_op" in content.text

    @pytest.mark.anyio
    async def test_immediate_result_error_prevents_main_tool_execution(self):
        """Test that immediate_result errors prevent the main tool from executing.

        When immediate_result fails, no async operation should be created and the main
        tool function should not be executed.
        """

        call_count = 0

        async def failing_immediate_fn(message: str) -> list[ContentBlock]:
            raise ValueError("Immediate failed")

        async def async_tool(message: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"Tool executed: {message}"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=failing_immediate_fn)
        async def tool_with_failing_immediate(message: str) -> str:
            """Tool with failing immediate result."""
            return await async_tool(message)

        # Verify the tool was registered
        internal_tool = mcp._tool_manager.get_tool("tool_with_failing_immediate")
        assert internal_tool is not None
        assert internal_tool.immediate_result == failing_immediate_fn

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # The call should return an error result due to immediate_result exception
            result = await client.call_tool("tool_with_failing_immediate", {"message": "test"})

            # Verify error result
            assert result.isError is True
            assert result.operation is None  # No operation created due to immediate_result failure
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            assert "Immediate result execution error" in content.text
            assert "Immediate failed" in content.text

            # Verify main tool was NOT executed due to immediate_result failure
            assert call_count == 0

    @pytest.mark.anyio
    async def test_immediate_result_mcp_error_passthrough(self):
        """Test that McpError from immediate_result is passed through with original error details."""

        async def mcp_error_immediate_fn(message: str) -> list[ContentBlock]:
            raise McpError(ErrorData(code=INVALID_PARAMS, message=f"Custom MCP error: {message}"))

        async def async_tool(message: str) -> str:
            return f"Completed: {message}"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=mcp_error_immediate_fn)
        async def tool_with_mcp_error_immediate(message: str) -> str:
            """Tool with immediate result that raises McpError."""
            return await async_tool(message)

        # Verify the tool was registered
        internal_tool = mcp._tool_manager.get_tool("tool_with_mcp_error_immediate")
        assert internal_tool is not None
        assert internal_tool.immediate_result == mcp_error_immediate_fn

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # The call should return an error result with the original McpError details
            result = await client.call_tool("tool_with_mcp_error_immediate", {"message": "test"})

            # Verify error result preserves the original McpError
            assert result.isError is True
            assert result.operation is None  # No operation created due to immediate_result failure
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            # The original McpError should be preserved, not wrapped in "Immediate result execution failed"
            assert "Custom MCP error: test" in content.text

    @pytest.mark.anyio
    async def test_generic_exception_wrapped_in_mcp_error(self):
        """Test that generic exceptions from immediate_result are wrapped in McpError with INTERNAL_ERROR code."""

        async def failing_immediate_fn(message: str) -> list[ContentBlock]:
            raise ValueError(f"Generic error: {message}")

        async def async_tool(message: str) -> str:
            return f"Completed: {message}"

        mcp = FastMCP()

        @mcp.tool(invocation_modes=["async"], immediate_result=failing_immediate_fn)
        async def tool_with_failing_immediate(message: str) -> str:
            """Tool with failing immediate result."""
            return await async_tool(message)

        # Test with "next" protocol version to enable async tools
        async with create_connected_server_and_client_session(mcp._mcp_server, protocol_version="next") as client:
            # The call should return an error result with wrapped exception
            result = await client.call_tool("tool_with_failing_immediate", {"message": "test"})

            # Verify error result wraps the exception
            assert result.isError is True
            assert result.operation is None  # No operation created due to immediate_result failure
            assert len(result.content) == 1
            content = result.content[0]
            assert content.type == "text"
            assert "Immediate result execution error" in content.text
            assert "Generic error: test" in content.text


class TestImmediateResultMetadata:
    """Test metadata handling for immediate_result functionality."""

    def test_immediate_result_stored_in_tool_object(self):
        """Test that immediate_result function is stored in Tool object."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()
        tool = manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=immediate_fn)

        # Verify immediate_result is stored in the Tool object
        assert tool.immediate_result == immediate_fn
        assert callable(tool.immediate_result)

    def test_tool_meta_field_preservation(self):
        """Test that existing meta field is preserved when immediate_result is added."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        # Add tool with both meta and immediate_result
        custom_meta = {"custom_key": "custom_value"}
        tool = manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=immediate_fn, meta=custom_meta)

        # Verify both meta and immediate_result are preserved
        assert tool.immediate_result == immediate_fn
        assert tool.meta is not None
        assert tool.meta["custom_key"] == "custom_value"

    def test_keep_alive_and_immediate_result_compatibility(self):
        """Test that keep_alive and immediate_result work together."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()

        # Add tool with both keep_alive and immediate_result
        tool = manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=immediate_fn, keep_alive=1800)

        # Verify both are set correctly
        assert tool.immediate_result == immediate_fn
        assert tool.meta is not None
        assert tool.meta["_keep_alive"] == 1800
        # immediate_result is no longer stored in meta, it's a direct field on the Tool object

    def test_immediate_result_stored_as_direct_field(self):
        """Test that immediate_result function is stored as a direct field on the Tool object."""

        async def immediate_fn() -> list[ContentBlock]:
            return [TextContent(type="text", text="immediate")]

        async def async_tool() -> str:
            return "async"

        manager = ToolManager()
        tool = manager.add_tool(async_tool, invocation_modes=["async"], immediate_result=immediate_fn)

        # Verify immediate_result is stored as a direct field on the Tool object
        assert tool.immediate_result == immediate_fn
        assert callable(tool.immediate_result)
        # immediate_result is no longer stored in meta field
