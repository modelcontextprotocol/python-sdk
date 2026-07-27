"""Capstone sticky-notes board on the lowlevel `Server`: handlers read lifespan state directly."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import mcp_types as types

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from stories._hosting import run_server_from_args


@dataclass
class Board:
    notes: dict[str, str] = field(default_factory=dict[str, str])
    _next: int = 1

    def claim_id(self) -> str:
        nid, self._next = str(self._next), self._next + 1
        return nid


CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"confirm": {"type": "boolean", "title": "Yes, permanently delete every sticky note"}},
    "required": ["confirm"],
}

TOOLS = [
    types.Tool(
        name="add_note",
        description="Add a sticky note.",
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
    types.Tool(
        name="remove_note",
        description="Remove one sticky note.",
        input_schema={"type": "object", "properties": {"note_id": {"type": "string"}}, "required": ["note_id"]},
    ),
    types.Tool(name="remove_all", description="Remove every note after confirmation.", input_schema={"type": "object"}),
]


def _result(text: str, structured: dict[str, Any]) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(text=text)], structured_content=structured)


def build_server() -> Server[Board]:
    @asynccontextmanager
    async def lifespan(_: Server[Board]) -> AsyncIterator[Board]:
        yield Board()

    async def list_tools(
        ctx: ServerRequestContext[Board], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS)

    async def list_resources(
        ctx: ServerRequestContext[Board], params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        board = ctx.lifespan_context
        return types.ListResourcesResult(
            resources=[
                types.Resource(uri=f"note:///{nid}", name=f"note-{nid}", mime_type="text/plain") for nid in board.notes
            ]
        )

    async def read_resource(
        ctx: ServerRequestContext[Board], params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        board = ctx.lifespan_context
        nid = str(params.uri).removeprefix("note:///")
        return types.ReadResourceResult(
            contents=[types.TextResourceContents(uri=params.uri, mime_type="text/plain", text=board.notes[nid])]
        )

    async def call_tool(ctx: ServerRequestContext[Board], params: types.CallToolRequestParams) -> types.CallToolResult:
        board = ctx.lifespan_context
        args = params.arguments or {}
        if params.name == "add_note":
            nid = board.claim_id()
            board.notes[nid] = args["text"]
            await ctx.session.send_resource_list_changed()
            return _result(f"added #{nid}", {"id": nid, "uri": f"note:///{nid}"})
        if params.name == "remove_note":
            removed = board.notes.pop(args["note_id"], None) is not None
            if removed:
                await ctx.session.send_resource_list_changed()
            return _result("removed" if removed else "not found", {"result": removed})
        if params.name == "remove_all":
            if not board.notes:
                return _result("empty", {"status": "empty", "removed": 0})
            answer = await ctx.session.elicit_form(
                f"Remove all {len(board.notes)} note(s)? This cannot be undone.", CONFIRM_SCHEMA, ctx.request_id
            )
            if answer.action == "cancel":
                return _result("cancelled", {"status": "cancelled", "removed": 0})
            if answer.action != "accept" or not (answer.content or {}).get("confirm"):
                return _result("declined", {"status": "declined", "removed": 0})
            count = len(board.notes)
            board.notes.clear()
            await ctx.session.send_resource_list_changed()
            return _result(f"cleared {count}", {"status": "cleared", "removed": count})
        raise NotImplementedError

    return Server(
        "stickynotes-example",
        lifespan=lifespan,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )


if __name__ == "__main__":
    run_server_from_args(build_server)
