"""
ETDI-enhanced MCP transports with request signing support
"""

import logging
from typing import Any, Dict, Optional
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.websocket import websocket_client

logger = logging.getLogger(__name__)


class ETDITransportWrapper:
    """Base wrapper for MCP transports with ETDI signature support"""
    
    def __init__(self, transport: Any):
        self.transport = transport
        self._signature_headers: Dict[str, str] = {}
    
    def add_signature_headers(self, headers: Dict[str, str]) -> None:
        """Add signature headers to be included in requests"""
        self._signature_headers.update(headers)
        logger.debug(f"Added signature headers: {list(headers.keys())}")
    
    def clear_signature_headers(self) -> None:
        """Clear stored signature headers"""
        self._signature_headers.clear()
    
    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to the wrapped transport"""
        return getattr(self.transport, name)


class ETDIStdioTransport(ETDITransportWrapper):
    """ETDI-enhanced stdio transport with signature support"""
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message with signature headers embedded"""
        if self._signature_headers:
            # Embed signature headers in the message envelope
            if 'etdi' not in message:
                message['etdi'] = {}
            message['etdi']['signature_headers'] = self._signature_headers.copy()
            logger.debug("Embedded signature headers in stdio message")
        
        # Send via original transport
        return await self.transport.send_message(message)


class ETDISSETransport(ETDITransportWrapper):
    """ETDI-enhanced SSE transport with signature support"""
    
    def __init__(self, transport: Any):
        super().__init__(transport)
        # Inject headers into the HTTP client if available
        if hasattr(transport, '_client'):
            self._inject_headers_into_client(transport._client)
    
    def _inject_headers_into_client(self, client: Any) -> None:
        """Inject signature headers into HTTP client"""
        if hasattr(client, 'headers'):
            client.headers.update(self._signature_headers)
            logger.debug("Injected signature headers into SSE HTTP client")
    
    def add_signature_headers(self, headers: Dict[str, str]) -> None:
        """Add signature headers and inject into HTTP client"""
        super().add_signature_headers(headers)
        if hasattr(self.transport, '_client'):
            self._inject_headers_into_client(self.transport._client)


class ETDIWebSocketTransport(ETDITransportWrapper):
    """ETDI-enhanced WebSocket transport with signature support"""
    
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send message with signature headers"""
        if self._signature_headers:
            # Add signature headers to WebSocket message
            if 'headers' not in message:
                message['headers'] = {}
            message['headers'].update(self._signature_headers)
            logger.debug("Added signature headers to WebSocket message")
        
        # Send via original transport
        return await self.transport.send_message(message)


def wrap_transport_with_etdi(transport: Any) -> ETDITransportWrapper:
    """
    Wrap an MCP transport with ETDI signature support
    
    Args:
        transport: Original MCP transport
        
    Returns:
        ETDI-enhanced transport wrapper
    """
    transport_type = type(transport).__name__
    
    if 'Stdio' in transport_type:
        return ETDIStdioTransport(transport)
    elif 'SSE' in transport_type or 'HTTP' in transport_type:
        return ETDISSETransport(transport)
    elif 'WebSocket' in transport_type or 'WS' in transport_type:
        return ETDIWebSocketTransport(transport)
    else:
        logger.warning(f"Unknown transport type {transport_type}, using base wrapper")
        return ETDITransportWrapper(transport)


async def etdi_stdio_client(*args, **kwargs) -> Any:
    """Create ETDI-enhanced stdio client"""
    session = await stdio_client(*args, **kwargs)
    if hasattr(session, '_transport'):
        session._transport = wrap_transport_with_etdi(session._transport)
    return session


async def etdi_sse_client(*args, **kwargs) -> Any:
    """Create ETDI-enhanced SSE client"""
    session = await sse_client(*args, **kwargs)
    if hasattr(session, '_transport'):
        session._transport = wrap_transport_with_etdi(session._transport)
    return session


async def etdi_websocket_client(*args, **kwargs) -> Any:
    """Create ETDI-enhanced WebSocket client"""
    session = await websocket_client(*args, **kwargs)
    if hasattr(session, '_transport'):
        session._transport = wrap_transport_with_etdi(session._transport)
    return session