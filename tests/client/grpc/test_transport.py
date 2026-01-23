"""
Tests for gRPC client transport.
"""

import pytest

from mcp.client.transport_session import ClientTransportSession


class TestGrpcTransportInterface:
    """Test that GrpcClientTransport implements ClientTransportSession correctly."""

    def test_import_without_grpc(self) -> None:
        """Test that import fails gracefully without grpcio."""
        # This test verifies the import guard works
        try:
            from mcp.client.grpc import GrpcClientTransport

            # If grpcio is installed, verify it's a ClientTransportSession
            assert issubclass(GrpcClientTransport, ClientTransportSession)
        except ImportError:
            # Expected if grpcio not installed
            pytest.skip("grpcio not installed")

    def test_implements_all_abstract_methods(self) -> None:
        """Verify GrpcClientTransport implements all required methods."""
        try:
            from mcp.client.grpc import GrpcClientTransport
        except ImportError:
            pytest.skip("grpcio not installed")

        # Get all abstract methods from ClientTransportSession
        import inspect

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
        try:
            from mcp.client.grpc import GrpcClientTransport
        except ImportError:
            pytest.skip("grpcio not installed")

        with pytest.raises(TypeError):
            GrpcClientTransport()  # type: ignore[call-arg]

    def test_accepts_target(self) -> None:
        """Test basic instantiation with target."""
        try:
            from mcp.client.grpc import GrpcClientTransport
        except ImportError:
            pytest.skip("grpcio not installed")

        transport = GrpcClientTransport("localhost:50051")
        assert transport._target == "localhost:50051"

    def test_not_connected_before_enter(self) -> None:
        """Test that transport is not connected before context manager."""
        try:
            from mcp.client.grpc import GrpcClientTransport
        except ImportError:
            pytest.skip("grpcio not installed")

        transport = GrpcClientTransport("localhost:50051")
        assert transport._channel is None
        assert transport._stub is None


# TODO: Add integration tests with a mock gRPC server
# These would test actual RPC calls and streaming behavior
