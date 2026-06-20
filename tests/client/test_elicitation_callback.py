from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from mcp import Client
from mcp.client.session import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared._context import RequestContext
from mcp.types import ElicitRequestParams, ElicitResult, TextContent


class AnswerSchema(BaseModel):
    answer: str = Field(description="The user's answer")


@pytest.mark.anyio
async def test_set_elicitation_callback():
    server = MCPServer("test")

    updated_answer = "Updated answer"

    async def updated_callback(
        context: RequestContext[ClientSession],
        params: ElicitRequestParams,
    ) -> ElicitResult:
        return ElicitResult(action="accept", content={"answer": updated_answer})

    @server.tool("ask")
    async def ask(prompt: str, ctx: Context) -> str:
        result = await ctx.elicit(message=prompt, schema=AnswerSchema)
        if result.action == "accept" and result.data:
            return result.data.answer
        return "no answer"  # pragma: no cover

    async with Client(server) as client:
        # Before setting callback — default rejects with error
        result = await client.call_tool("ask", {"prompt": "question?"})
        assert result.is_error is True

        # Set new callback — should succeed
        client.session.set_elicitation_callback(updated_callback)
        result = await client.call_tool("ask", {"prompt": "question?"})
        assert result.is_error is False
        assert isinstance(result.content[0], TextContent)
        assert result.content[0].text == updated_answer

        # Reset to None — back to default error
        client.session.set_elicitation_callback(None)
        result = await client.call_tool("ask", {"prompt": "question?"})
        assert result.is_error is True
