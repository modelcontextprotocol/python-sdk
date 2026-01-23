"""
Tests for gRPC client transport.
"""

from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from mcp.client.transport_session import ClientTransportSession


class TestGrpcTransportInterface:
    """Test that GrpcClientTransport implements ClientTransportSession correctly."""

    def test_import_with_grpc(self) -> None:
        """Test that GrpcClientTransport is available and is a ClientTransportSession."""
        from mcp.client.grpc import GrpcClientTransport

        assert issubclass(GrpcClientTransport, ClientTransportSession)

    def test_implements_all_abstract_methods(self) -> None:
        """Verify GrpcClientTransport implements all required methods."""
        # Get all abstract methods from ClientTransportSession
        import inspect

        from mcp.client.grpc import GrpcClientTransport

        abstract_methods = {
            name
            for name, method in inspect.getmembers(
                ClientTransportSession, predicate=inspect.isfunction
            )
            if getattr(method, "__isabstractmethod__", False)
        }

        # Get all methods implemented by GrpcClientTransport
        implemented_methods = {
            name
            for name, _ in inspect.getmembers(
                GrpcClientTransport, predicate=inspect.isfunction
            )
        }

        # Verify all abstract methods are implemented
        missing = abstract_methods - implemented_methods
        assert not missing, f"Missing implementations: {missing}"


class TestGrpcTransportInstantiation:
    """Test GrpcClientTransport instantiation."""

    def test_requires_target(self) -> None:
        """Test that target is required."""
        from mcp.client.grpc import GrpcClientTransport

        with pytest.raises(TypeError):
            GrpcClientTransport()  # type: ignore[call-arg]

    def test_accepts_target(self) -> None:
        """Test basic instantiation with target."""
        from mcp.client.grpc import GrpcClientTransport

        transport = GrpcClientTransport("localhost:50051")
        assert transport._target == "localhost:50051"

    def test_not_connected_before_enter(self) -> None:
        """Test that transport is not connected before context manager."""
        from mcp.client.grpc import GrpcClientTransport

        transport = GrpcClientTransport("localhost:50051")
        assert transport._channel is None
        assert transport._stub is None


@pytest.mark.anyio
class TestGrpcTransportFunctionality:
    """Test GrpcClientTransport functionality using mocks."""

    async def test_initialize(self) -> None:
        """Test initialize call."""
        from mcp.client.grpc import GrpcClientTransport
        from mcp.v1.mcp_pb2 import InitializeResponse

        transport = GrpcClientTransport("localhost:50051")
        transport._stub = MagicMock()
        
        mock_response = InitializeResponse(
            protocol_version="2024-11-05",
            instructions="Test instructions",
        )
        mock_response.server_info.name = "test-server"
        mock_response.server_info.version = "1.0.0"
        
        transport._stub.Initialize = AsyncMock(return_value=mock_response)

        # Mock __aenter__ to avoid channel creation
        transport._session_task = MagicMock() # Avoid task creation
        
        result = await transport.initialize()
        
        assert result.protocolVersion == "2024-11-05"
        assert result.serverInfo.name == "test-server"
        assert result.instructions == "Test instructions"
        transport._stub.Initialize.assert_called_once()

    async def test_ping(self) -> None:
        """Test ping call."""
        from mcp.client.grpc import GrpcClientTransport
        from mcp.v1.mcp_pb2 import PingResponse

        transport = GrpcClientTransport("localhost:50051")
        transport._stub = MagicMock()
        transport._stub.Ping = AsyncMock(return_value=PingResponse())

        await transport.send_ping()
        transport._stub.Ping.assert_called_once()

    async def test_error_mapping(self) -> None:
        """Test gRPC to MCP error mapping."""
        from mcp.client.grpc import GrpcClientTransport

        transport = GrpcClientTransport("localhost:50051")
        
        # Mock a gRPC error using a class that implements code() and details()
        class MockRpcError(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.NOT_FOUND
            def details(self):
                return "Not found"
        
        mock_error = MockRpcError()
        
        mapped_error = transport._map_error(mock_error)
        assert isinstance(mapped_error, ValueError)
        assert "Not found" in str(mapped_error)
