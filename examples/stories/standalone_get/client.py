"""Receive `notifications/resources/list_changed` over the standalone GET stream, then re-list."""

from typing import Any

import anyio

from mcp import types
from mcp.client import Client
from stories._harness import connect_from_args, run_client

# Shared between the `message_handler` (wired at connect time) and `scenario()`.
# Reset per leg by `client_kw()` so each (variant × era) starts clean.
_received: list[types.ResourceListChangedNotification] = []
_seen: list[anyio.Event] = []


async def _on_message(message: object) -> None:
    if isinstance(message, types.ResourceListChangedNotification):
        _received.append(message)
        _seen[0].set()


def client_kw() -> dict[str, Any]:
    _received[:] = []
    _seen[:] = [anyio.Event()]
    return {"message_handler": _on_message}


async def scenario(client: Client) -> None:
    before = await client.list_resources()
    assert len(before.resources) >= 1, before

    result = await client.call_tool("add_note", {"content": "hello"})
    assert not result.is_error, result

    # The notification rides the standalone GET stream, not the call's POST stream —
    # delivery order vs the tool result is not guaranteed, so wait.
    with anyio.fail_after(5):
        await _seen[0].wait()
    assert len(_received) == 1, _received

    after = await client.list_resources()
    assert len(after.resources) == len(before.resources) + 1, after
    assert {r.name for r in after.resources} >= {"initial", "note-1"}


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), **client_kw())
