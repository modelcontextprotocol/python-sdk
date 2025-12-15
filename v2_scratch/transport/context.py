from dataclasses import dataclass

from v2_scratch.transport.transport_interface import Transport
from v2_scratch.types import NotificationParams, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse


@dataclass
class Context:
    transport: Transport

    async def send_notification(self, params: NotificationParams) -> None:
        # Build JSONRPCNotification from params and send
        notification = JSONRPCNotification(
            method=params.method,
            params=params.model_dump(exclude={"method"}),
        )
        await self.transport.send(notification)

    async def send_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        return await self.transport.send_request(request)
