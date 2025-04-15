"""
Message Dispatch Module for MCP Server

This module implements dispatch interfaces for handling
messages between clients and servers.
"""

from mcp.server.message_queue.base import InMemoryMessageDispatch, MessageDispatch

# Try to import Redis implementation if available
try:
    from mcp.server.message_queue.redis import RedisMessageDispatch
except ImportError:
    RedisMessageDispatch = None

__all__ = ["MessageDispatch", "InMemoryMessageDispatch", "RedisMessageDispatch"]
