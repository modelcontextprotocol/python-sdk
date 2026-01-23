"""
gRPC transport implementation for MCP client.

This module provides a gRPC-based transport that implements the
ClientTransportSession interface, enabling MCP communication over
gRPC with HTTP/2 bidirectional streaming.
"""

from mcp.client.grpc.transport import GrpcClientTransport

__all__ = ["GrpcClientTransport"]
