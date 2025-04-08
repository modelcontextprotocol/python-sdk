"""
Message Queue Module for MCP Server

This module implements queue interfaces for handling
messages between clients and servers.
"""

from mcp.server.message_queue.base import InMemoryMessageQueue, MessageQueue

# Try to import Redis implementation if available
try:
    from mcp.server.message_queue.redis import RedisMessageQueue
except ImportError:
    RedisMessageQueue = None

__all__ = ["MessageQueue", "InMemoryMessageQueue", "RedisMessageQueue"]
