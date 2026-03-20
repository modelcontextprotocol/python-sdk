"""The minimal MRTR lowlevel server — the simple-tool equivalent.

No version checks, no comparison framing. Just the two moves every MRTR
handler makes:

  1. Check ``params.input_responses`` for the answer to a prior ask.
  2. If it's not there, return ``IncompleteResult`` with the ask embedded.

The client SDK (``mcp.client.Client.call_tool``) drives the retry loop —
this handler is invoked once per round with whatever the client collected.

Run against the in-memory client:

    uv run python -m mrtr_options.basic
"""

from __future__ import annotations

import anyio

from mcp import types
from mcp.client import Client
from mcp.client.context import ClientRequestContext
from mcp.server import Server, ServerRequestContext


async def on_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name="get_weather",
                description="Look up weather for a location. Asks which units you want.",
                input_schema={
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            )
        ]
    )


async def on_call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult | types.IncompleteResult:
    """The MRTR tool handler. Called once per round."""
    location = (params.arguments or {}).get("location", "?")

    # ───────────────────────────────────────────────────────────────────────
    # Step 1: check if the client has already answered our question.
    #
    # ``input_responses`` is a dict keyed by the same keys we used in
    # ``input_requests`` on the prior round. Each value is the raw result
    # the client produced (ElicitResult, CreateMessageResult, ListRootsResult
    # — serialized to dict form over the wire).
    #
    # On the first round, ``input_responses`` is None. On subsequent rounds,
    # it contains ONLY the answers to the most recent round's asks — not
    # accumulated across rounds. If you need to accumulate, encode it in
    # ``request_state`` (see option_f_ctx_once.py / option_g_tool_builder.py).
    # ───────────────────────────────────────────────────────────────────────
    responses = params.input_responses or {}
    prefs = responses.get("unit_prefs")

    if prefs is None or prefs.get("action") != "accept":
        # ───────────────────────────────────────────────────────────────────
        # Step 2: ask. Return IncompleteResult with the embedded request.
        #
        # The client SDK receives this, dispatches the embedded ElicitRequest
        # to its elicitation_callback, and re-invokes this handler with the
        # answer in input_responses["unit_prefs"].
        #
        # Keys are server-assigned and opaque to the client. Pick whatever
        # makes the code readable — they just need to be consistent between
        # the ask and the check above.
        # ───────────────────────────────────────────────────────────────────
        return types.IncompleteResult(
            input_requests={
                "unit_prefs": types.ElicitRequest(
                    params=types.ElicitRequestFormParams(
                        message="Which units for the temperature?",
                        requested_schema={
                            "type": "object",
                            "properties": {"units": {"type": "string", "enum": ["metric", "imperial"]}},
                            "required": ["units"],
                        },
                    )
                )
            },
            # request_state is optional. Use it for anything that must
            # survive across rounds without server-side storage — e.g.
            # partially-computed results, progress markers, or (in F/G)
            # idempotency guards. The client echoes it verbatim.
            request_state=None,
        )

    # ───────────────────────────────────────────────────────────────────────
    # Step 3: we have the answer. Compute and return a normal result.
    # ───────────────────────────────────────────────────────────────────────
    units = prefs["content"]["units"]
    temp = "22°C" if units == "metric" else "72°F"
    return types.CallToolResult(content=[types.TextContent(text=f"Weather in {location}: {temp}, partly cloudy.")])


server = Server("mrtr-basic", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


# ─── Demo driver ─────────────────────────────────────────────────────────────


async def elicitation_callback(context: ClientRequestContext, params: types.ElicitRequestParams) -> types.ElicitResult:
    """What the app developer writes. Same signature as SSE-era callbacks."""
    assert isinstance(params, types.ElicitRequestFormParams)
    print(f"[client] server asks: {params.message}")
    # A real client presents params.requested_schema as a form. We hard-code.
    return types.ElicitResult(action="accept", content={"units": "metric"})


async def main() -> None:
    async with Client(server, elicitation_callback=elicitation_callback) as client:
        result = await client.call_tool("get_weather", {"location": "Tokyo"})
        print(f"[client] result: {result.content[0].text}")  # type: ignore[union-attr]


if __name__ == "__main__":
    anyio.run(main)
