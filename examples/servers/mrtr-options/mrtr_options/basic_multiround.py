"""Multi-round MRTR with request_state accumulation.

This is the ADO-custom-rules example from the SEP, translated. Resolving
a work item triggers cascading required fields:

  Rule 1: State → "Resolved" requires a Resolution field
  Rule 2: Resolution = "Duplicate" requires a "Duplicate Of" link

The server learns Rule 2 is needed only after the user answers Rule 1.
Two rounds of elicitation. The Rule 1 answer must survive across rounds
*without server-side storage* — that's what ``request_state`` is for.

Key point: ``input_responses`` carries only the *latest* round's answers.
Round 2's retry has ``{"duplicate_of": ...}`` but NOT ``{"resolution": ...}``.
Anything the server needs to keep must be encoded in ``request_state``,
which the client echoes verbatim.

Run against the in-memory client:

    uv run python -m mrtr_options.basic_multiround
"""

from __future__ import annotations

import base64
import json
from typing import Any

import anyio

from mcp import types
from mcp.client import Client
from mcp.client.context import ClientRequestContext
from mcp.server import Server, ServerRequestContext


def encode_state(state: dict[str, Any]) -> str:
    """Serialize state for the round trip through the client.

    Plain base64-JSON here. A production server handling sensitive data
    MUST sign this — the client is an untrusted intermediary and could
    forge or replay state otherwise. See SEP-2322 §Security Implications.
    """
    return base64.b64encode(json.dumps(state).encode()).decode()


def decode_state(blob: str | None) -> dict[str, Any]:
    if not blob:
        return {}
    return json.loads(base64.b64decode(blob))


def ask(message: str, field: str) -> types.ElicitRequest:
    """Build a form-mode elicitation for a single string field."""
    return types.ElicitRequest(
        params=types.ElicitRequestFormParams(
            message=message,
            requested_schema={
                "type": "object",
                "properties": {field: {"type": "string"}},
                "required": [field],
            },
        )
    )


async def on_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="resolve_work_item",
                description="Resolve a work item. May need cascading follow-up fields.",
                input_schema={
                    "type": "object",
                    "properties": {"work_item_id": {"type": "integer"}},
                    "required": ["work_item_id"],
                },
            )
        ]
    )


async def on_call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    args = params.arguments or {}
    work_item_id = args.get("work_item_id", 0)
    responses = params.input_responses or {}
    state = decode_state(params.request_state)

    # ───────────────────────────────────────────────────────────────────────
    # Round 1: State → Resolved triggers Rule 1 (require Resolution).
    #
    # If we don't yet have the resolution — neither in this round's
    # input_responses nor in accumulated state — ask for it.
    # ───────────────────────────────────────────────────────────────────────
    resolution = state.get("resolution")
    if not resolution:
        resp = responses.get("resolution")
        if not resp or resp.get("action") != "accept":
            return types.IncompleteResult(
                input_requests={
                    "resolution": ask(
                        f"Resolving #{work_item_id} requires a resolution. Fixed, Won't Fix, Duplicate, or By Design?",
                        "resolution",
                    )
                },
                # No state yet — the original tool arguments are re-sent on
                # retry, so we don't need to encode anything for round 1.
            )
        resolution = resp["content"]["resolution"]

    # ───────────────────────────────────────────────────────────────────────
    # Round 2: Resolution = "Duplicate" triggers Rule 2 (require link).
    #
    # If the resolution is Duplicate and we don't yet have the link, ask
    # for it — but encode the already-gathered resolution in request_state
    # so it survives the round trip regardless of which server instance
    # handles the next retry.
    # ───────────────────────────────────────────────────────────────────────
    if resolution == "Duplicate":
        resp = responses.get("duplicate_of")
        if not resp or resp.get("action") != "accept":
            return types.IncompleteResult(
                input_requests={"duplicate_of": ask("Which work item is the original?", "duplicate_of")},
                request_state=encode_state({"resolution": resolution}),
            )
        dup = resp["content"]["duplicate_of"]
        text = f"#{work_item_id} resolved as Duplicate of #{dup}."
    else:
        text = f"#{work_item_id} resolved as {resolution}."

    return types.CallToolResult(content=[types.TextContent(text=text)])


server = Server("mrtr-multiround", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


# ─── Demo driver ─────────────────────────────────────────────────────────────


ANSWERS = {
    "resolution": "Duplicate",
    "duplicate_of": "4301",
}


async def elicitation_callback(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    assert isinstance(params, types.ElicitRequestFormParams)
    print(f"[client] server asks: {params.message}")
    # Pick the field name from the schema and answer from our table.
    field = next(iter(params.requested_schema["properties"]))
    answer = ANSWERS[field]
    print(f"[client] answering {field}={answer}")
    return types.ElicitResult(action="accept", content={field: answer})


async def main() -> None:
    async with Client(server, elicitation_callback=elicitation_callback) as client:
        result = await client.call_tool("resolve_work_item", {"work_item_id": 4522})
        print(f"[client] final: {result.content[0].text}")  # type: ignore[union-attr]


if __name__ == "__main__":
    anyio.run(main)
