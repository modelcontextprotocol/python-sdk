"""
This module provides simpler types to use with the server for managing prompts
and tools.
"""

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import BaseModel

from mcp.types import JSONRPCMessage, ServerCapabilities

ReadStream = MemoryObjectReceiveStream[JSONRPCMessage | Exception]
ReadStreamWriter = MemoryObjectSendStream[JSONRPCMessage | Exception]
WriteStream = MemoryObjectSendStream[JSONRPCMessage]
WriteStreamReader = MemoryObjectReceiveStream[JSONRPCMessage]


class InitializationOptions(BaseModel):
    server_name: str
    server_version: str
    capabilities: ServerCapabilities
    instructions: str | None = None
