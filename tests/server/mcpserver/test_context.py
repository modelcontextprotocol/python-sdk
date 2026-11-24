"""Tests for MCPServer Context properties and request ID correlation."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver.context import Context


class _Answer(BaseModel):
    value: str


def _make_context(request_id: str | int | None) -> tuple[Context, MagicMock]:
    session = MagicMock()
    session.send_log_message = AsyncMock()
    session.elicit_form = AsyncMock(return_value=MagicMock(action="decline"))
    req_ctx = ServerRequestContext(
        request_id=request_id,
        meta=None,
        session=session,
        lifespan_context={},
        protocol_version="2025-11-25",
        method="tools/call",
    )
    return Context(request_context=req_ctx), session


@pytest.mark.parametrize("request_id", [42, "req-1", None])
def test_context_request_id_preserves_type(request_id: str | int | None) -> None:
    ctx, _ = _make_context(request_id)
    assert ctx.request_id == request_id
    if request_id is not None:
        assert type(ctx.request_id) is type(request_id)


@pytest.mark.anyio
@pytest.mark.parametrize("request_id", [42, "req-1", None])
async def test_context_log_and_elicit_preserve_related_request_id(request_id: str | int | None) -> None:
    ctx, session = _make_context(request_id)

    await ctx.log("info", "hello")  # pyright: ignore[reportDeprecated]
    session.send_log_message.assert_awaited_once()
    assert session.send_log_message.await_args.kwargs["related_request_id"] == request_id

    await ctx.elicit("Enter value", _Answer)
    session.elicit_form.assert_awaited_once()
    assert session.elicit_form.await_args is not None
    assert session.elicit_form.await_args.kwargs["related_request_id"] == request_id
    assert session.send_log_message.await_args is not None
