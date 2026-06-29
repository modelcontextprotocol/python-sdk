"""Capstone sticky-notes board: tools mutate lifespan state, one resource per note,
`resources/list_changed` on add/remove, elicitation-guarded clear."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from pydantic import BaseModel

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from stories._hosting import run_server_from_args


@dataclass
class Board:
    notes: dict[str, str] = field(default_factory=dict[str, str])
    _next: int = 1

    def claim_id(self) -> str:
        nid, self._next = str(self._next), self._next + 1
        return nid


class AddResult(BaseModel):
    id: str
    uri: str


class ClearResult(BaseModel):
    status: str
    removed: int


class ConfirmClear(BaseModel):
    confirm: bool


def build_server() -> MCPServer:
    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[Board]:
        yield Board()

    mcp = MCPServer("stickynotes-example", lifespan=lifespan)

    def unregister_note(note_id: str) -> None:
        # Don't copy this: `MCPServer` has no public `remove_resource()` yet, so this reaches a
        # private attribute. `server_lowlevel.py` shows the clean shape — `on_list_resources`
        # rebuilds the list from the board on every call, so removal never touches a registry.
        mcp._resource_manager._resources.pop(f"note:///{note_id}", None)  # pyright: ignore[reportPrivateUsage]

    @mcp.tool()
    async def add_note(text: str, ctx: Context[Board]) -> AddResult:
        """Add a sticky note and register a `note:///{id}` resource for it."""
        board = ctx.request_context.lifespan_context
        note_id = board.claim_id()
        uri = f"note:///{note_id}"
        board.notes[note_id] = text
        mcp.add_resource(
            FunctionResource(uri=uri, name=f"note-{note_id}", mime_type="text/plain", fn=lambda: board.notes[note_id])
        )
        await ctx.session.send_resource_list_changed()
        return AddResult(id=note_id, uri=uri)

    @mcp.tool()
    async def remove_note(note_id: str, ctx: Context[Board]) -> bool:
        """Remove one sticky note and unregister its resource."""
        board = ctx.request_context.lifespan_context
        removed = board.notes.pop(note_id, None) is not None
        if removed:
            unregister_note(note_id)
            await ctx.session.send_resource_list_changed()
        return removed

    @mcp.tool()
    async def remove_all(ctx: Context[Board]) -> ClearResult:
        """Remove every note after a confirmed form-mode elicitation (handshake-era only)."""
        board = ctx.request_context.lifespan_context
        if not board.notes:
            return ClearResult(status="empty", removed=0)
        answer = await ctx.elicit(f"Remove all {len(board.notes)} note(s)? This cannot be undone.", ConfirmClear)
        if answer.action == "cancel":
            return ClearResult(status="cancelled", removed=0)
        if answer.action != "accept" or not answer.data.confirm:
            return ClearResult(status="declined", removed=0)
        count = len(board.notes)
        for nid in list(board.notes):
            unregister_note(nid)
        board.notes.clear()
        await ctx.session.send_resource_list_changed()
        return ClearResult(status="cleared", removed=count)

    return mcp


if __name__ == "__main__":
    run_server_from_args(build_server)
