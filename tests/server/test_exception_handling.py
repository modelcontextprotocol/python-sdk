"""Test exception handling in lowlevel server message processing."""

import logging
from unittest.mock import Mock

import anyio
import pytest

from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage
from mcp.types import ServerCapabilities


@pytest.mark.anyio
async def test_handle_message_with_exception_logging(caplog):
    """Test that Exception instances passed to _handle_message are properly logged."""
    server = Server("test")
    
    # Create in-memory streams for testing
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    
    # Create a server session
    session = ServerSession(
        read_stream=client_to_server_receive,
        write_stream=server_to_client_send,
        init_options=InitializationOptions(
            server_name="test",
            server_version="1.0.0",
            capabilities=ServerCapabilities(),
        ),
    )
    
    # Create a test exception
    test_exception = ValueError("Test exception for logging")
    
    # Test the _handle_message method directly with an Exception
    with caplog.at_level(logging.ERROR):
        await server._handle_message(
            message=test_exception,
            session=session,
            lifespan_context=None,
            raise_exceptions=False,
        )
    
    # Verify that the exception was logged
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR
    assert "Error in message processing" in record.getMessage()
    assert "Test exception for logging" in record.getMessage()


@pytest.mark.anyio
async def test_handle_message_with_exception_raising():
    """Test that Exception instances are re-raised when raise_exceptions=True."""
    server = Server("test")
    
    # Create in-memory streams for testing
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    
    # Create a server session
    session = ServerSession(
        read_stream=client_to_server_receive,
        write_stream=server_to_client_send,
        init_options=InitializationOptions(
            server_name="test",
            server_version="1.0.0",
            capabilities=ServerCapabilities(),
        ),
    )
    
    # Create a test exception
    test_exception = ValueError("Test exception for raising")
    
    # Test that the exception is re-raised when raise_exceptions=True
    with pytest.raises(ValueError, match="Test exception for raising"):
        await server._handle_message(
            message=test_exception,
            session=session,
            lifespan_context=None,
            raise_exceptions=True,
        )


@pytest.mark.anyio
async def test_handle_message_with_exception_no_raise():
    """Test that Exception instances are not re-raised when raise_exceptions=False."""
    server = Server("test")
    
    # Create in-memory streams for testing
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](10)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](10)
    
    # Create a server session
    session = ServerSession(
        read_stream=client_to_server_receive,
        write_stream=server_to_client_send,
        init_options=InitializationOptions(
            server_name="test",
            server_version="1.0.0",
            capabilities=ServerCapabilities(),
        ),
    )
    
    # Create a test exception
    test_exception = RuntimeError("Test exception for no raising")
    
    # Test that the exception is not re-raised when raise_exceptions=False
    # This should not raise an exception
    await server._handle_message(
        message=test_exception,
        session=session,
        lifespan_context=None,
        raise_exceptions=False,
    )
    # If we reach this point, the test passed 