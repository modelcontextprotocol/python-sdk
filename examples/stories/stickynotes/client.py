"""Drive the sticky-notes board end to end and prove `remove_all` clears only on a confirmed elicitation."""

from typing import Any

import anyio

from mcp import types
from mcp.client import Client, ClientRequestContext
from mcp.shared.version import HANDSHAKE_PROTOCOL_VERSIONS
from stories._harness import connect_from_args, run_client

# Shared state between the client callbacks (wired at connect time) and `scenario()`.
# Reset per leg by `client_kw()` so each (transport × era × variant) starts clean.
_elicit_answer: list[str] = ["cancel"]
_list_changed: list[anyio.Event] = []


async def _on_elicit(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    if _elicit_answer[0] == "cancel":
        return types.ElicitResult(action="cancel")
    return types.ElicitResult(action="accept", content={"confirm": _elicit_answer[0] == "confirm"})


async def _on_message(message: object) -> None:
    if isinstance(message, types.ResourceListChangedNotification):
        _list_changed[0].set()


def client_kw() -> dict[str, Any]:
    _elicit_answer[:] = ["cancel"]
    _list_changed[:] = [anyio.Event()]
    return {"elicitation_callback": _on_elicit, "message_handler": _on_message}


async def scenario(client: Client) -> None:
    legacy = client.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS

    # Add two notes.
    first = await client.call_tool("add_note", {"text": "Buy milk"})
    assert first.structured_content is not None
    first_id, first_uri = first.structured_content["id"], first.structured_content["uri"]
    assert first_uri.startswith("note:///")
    second = await client.call_tool("add_note", {"text": "Walk the dog"})
    assert second.structured_content is not None
    second_id, second_uri = second.structured_content["id"], second.structured_content["uri"]
    assert first_id != second_id

    # List + read — both notes appear as resources; first reads back its text.
    listed = await client.list_resources()
    uris = {str(r.uri) for r in listed.resources}
    assert first_uri in uris and second_uri in uris, uris
    read = await client.read_resource(first_uri)
    assert isinstance(read.contents[0], types.TextResourceContents)
    assert read.contents[0].text == "Buy milk"

    # list_changed rides the standalone stream — only deliverable on a legacy-era connection.
    if legacy:
        with anyio.fail_after(5):
            await _list_changed[0].wait()

    # Remove one.
    removed = await client.call_tool("remove_note", {"note_id": first_id})
    assert removed.structured_content == {"result": True}
    after = await client.list_resources()
    assert first_uri not in {str(r.uri) for r in after.resources}

    # remove_all uses push-style elicitation: legacy-era only (modern equivalent lands with the mrtr/ story).
    if not legacy:
        gone = await client.call_tool("remove_note", {"note_id": second_id})
        assert gone.structured_content == {"result": True}
        return

    _elicit_answer[0] = "cancel"
    cancelled = await client.call_tool("remove_all", {})
    assert cancelled.structured_content == {"status": "cancelled", "removed": 0}

    _elicit_answer[0] = "unchecked"
    declined = await client.call_tool("remove_all", {})
    assert declined.structured_content == {"status": "declined", "removed": 0}

    _elicit_answer[0] = "confirm"
    cleared = await client.call_tool("remove_all", {})
    assert cleared.structured_content == {"status": "cleared", "removed": 1}
    final = await client.list_resources()
    assert not [r for r in final.resources if str(r.uri).startswith("note:///")]

    empty = await client.call_tool("remove_all", {})
    assert empty.structured_content == {"status": "empty", "removed": 0}


if __name__ == "__main__":
    run_client(scenario, connect=connect_from_args(__file__), **client_kw())
