from abc import ABC
from collections.abc import AsyncIterator

from mcp_v2.types.json_rpc import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse


class Transport(ABC):
    async def send(self, message: JSONRPCMessage) -> None: ...
    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse: ...
    def __aiter__(self) -> AsyncIterator[JSONRPCMessage]: ...
