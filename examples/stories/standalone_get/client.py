"""Receive `notifications/resources/list_changed` over the standalone GET stream, then re-list."""

import anyio

from mcp import types
from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    # `message_handler` is constructor-only on `Client`, so the event it sets
    # has to exist before the connection does.
    received: list[types.ResourceListChangedNotification] = []
    seen = anyio.Event()

    async def on_message(message: object) -> None:
        if isinstance(message, types.ResourceListChangedNotification):
            received.append(message)
            seen.set()

    async with Client(target, mode=mode, message_handler=on_message) as client:
        before = await client.list_resources()
        assert len(before.resources) >= 1, before

        result = await client.call_tool("add_note", {"content": "hello"})
        assert not result.is_error, result

        # The notification rides the standalone GET stream, not the call's POST stream —
        # delivery order vs the tool result is not guaranteed, so wait.
        with anyio.fail_after(5):
            await seen.wait()
        assert len(received) == 1, received

        after = await client.list_resources()
        assert len(after.resources) == len(before.resources) + 1, after
        assert {r.name for r in after.resources} >= {"initial", "note-1"}


if __name__ == "__main__":
    run_client(main)
