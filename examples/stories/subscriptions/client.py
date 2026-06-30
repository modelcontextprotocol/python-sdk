"""Open a `subscriptions/listen` stream, watch one URI and the tool list, then close it."""

import anyio
import mcp_types as types

from mcp.client import Client
from stories._harness import Target, run_client

SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"


async def main(target: Target, *, mode: str = "auto") -> None:
    # Stream frames arrive as ordinary server notifications; `message_handler`
    # is constructor-only on `Client`, so the list it fills exists first.
    received: list[types.ServerNotification] = []
    arrival = anyio.Event()

    async def on_message(message: object) -> None:
        nonlocal arrival
        if isinstance(
            message,
            types.SubscriptionsAcknowledgedNotification
            | types.ResourceUpdatedNotification
            | types.ToolListChangedNotification,
        ):
            received.append(message)
            arrival.set()
            arrival = anyio.Event()

    async def wait_for(count: int) -> None:
        with anyio.fail_after(10):
            while len(received) < count:
                await arrival.wait()

    async with Client(target, mode=mode, message_handler=on_message) as client:
        before = await client.list_tools()
        assert "search" not in {tool.name for tool in before.tools}

        async with anyio.create_task_group() as tg:
            # There is no client-side listen API yet, so the story drops to the
            # `client.session` escape hatch: the request parks for the stream's
            # lifetime, so it runs as a task and the client closes the stream by
            # cancelling it (the spec's client-side close).
            async def listen() -> None:
                request = types.SubscriptionsListenRequest(
                    params=types.SubscriptionsListenRequestParams(
                        notifications=types.SubscriptionFilter(
                            tools_list_changed=True, resource_subscriptions=["note://todo"]
                        )
                    )
                )
                await client.session.send_request(request, types.SubscriptionsListenResult)

            tg.start_soon(listen)

            # ── the ack is the first frame: it echoes the honored filter, tagged ──
            await wait_for(1)
            ack = received[0]
            assert isinstance(ack, types.SubscriptionsAcknowledgedNotification), ack
            assert ack.params.notifications.tools_list_changed is True
            assert ack.params.notifications.resource_subscriptions == ["note://todo"]
            assert ack.params.meta is not None and SUBSCRIPTION_ID in ack.params.meta

            # ── exact-URI filtering: an unsubscribed note edit stays silent ──
            await client.call_tool("edit_note", {"name": "journal", "text": "day two"})
            # ── the subscribed URI delivers, carrying the same subscription id ──
            await client.call_tool("edit_note", {"name": "todo", "text": "water plants"})
            await wait_for(2)
            updated = received[1]
            assert isinstance(updated, types.ResourceUpdatedNotification), updated
            assert updated.params.uri == "note://todo"
            assert updated.params.meta == ack.params.meta
            assert len(received) == 2, "the journal edit must not have been delivered"

            # ── a runtime tool registration announces itself ──
            await client.call_tool("enable_search", {})
            await wait_for(3)
            assert isinstance(received[2], types.ToolListChangedNotification), received[2]

            # The client is done listening: closing the stream is cancelling the
            # parked request's scope.
            tg.cancel_scope.cancel()

        # list_changed told us to re-fetch - the new tool is callable, and the
        # session outlives the closed stream.
        tools = await client.list_tools()
        assert "search" in {tool.name for tool in tools.tools}
        result = await client.call_tool("search", {"query": "water"})
        content = result.content[0]
        assert isinstance(content, types.TextContent) and content.text == "todo", result


if __name__ == "__main__":
    run_client(main)
