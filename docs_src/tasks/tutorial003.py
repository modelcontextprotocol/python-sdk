from typing import cast

import mcp_types as types

from mcp import Client
from mcp.client import TasksExtension
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import CreateTaskResult, Tasks
from mcp.shared.tasks import GetTaskRequest, GetTaskRequestParams, GetTaskResult

mcp = MCPServer("bakery", extensions=[Tasks()])


@mcp.tool()
def bake(flavor: str) -> str:
    """Bake a cake."""
    return f"One {flavor} cake, ready."


async def main() -> None:
    async with Client(mcp, extensions=[TasksExtension()]) as client:
        created = await client.session.call_tool("bake", {"flavor": "mocha"}, allow_claimed=True)
        assert isinstance(created, CreateTaskResult)
        print(created.status)
        # completed

        request = GetTaskRequest(params=GetTaskRequestParams(task_id=created.task_id))
        polled = await client.session.send_request(cast("types.ClientRequest", request), GetTaskResult)
        assert polled.result is not None
        print(polled.result["content"])
        # [{'text': 'One mocha cake, ready.', 'type': 'text'}]
