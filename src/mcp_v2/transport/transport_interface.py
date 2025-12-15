from collections.abc import AsyncIterator
from typing import Protocol

from mcp_v2.types.json_rpc import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse


class Transport(Protocol):
    async def send(self, message: JSONRPCMessage) -> None: ...
    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse: ...
    def __aiter__(self) -> AsyncIterator[JSONRPCMessage]: ...
