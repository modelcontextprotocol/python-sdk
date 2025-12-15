from dataclasses import dataclass

from mcp_v2.transport.transport_interface import Transport
from mcp_v2.types.base import NotificationParams
from mcp_v2.types.json_rpc import JSONRPCNotification, JSONRPCRequest, JSONRPCResponse


@dataclass
class Context:
    transport: Transport

    async def send_notification(self, method: str, params: NotificationParams | None = None) -> None:
        # Build JSONRPCNotification from params and send
        notification = JSONRPCNotification(
            method=method,
            params=params.model_dump() if params else None,
        )
        await self.transport.send(notification)

    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        return await self.transport.send_request(request)
