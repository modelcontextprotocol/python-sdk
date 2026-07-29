from mcp import Client
from mcp.client import TasksExtension
from mcp.client.tasks import get_task, wait_task
from mcp.server.mcpserver import MCPServer
from mcp.server.tasks import Tasks
from mcp.shared.tasks import CreateTaskResult

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

        polled = await get_task(client.session, created.task_id)
        assert polled.result is not None
        print(polled.result["content"])
        # [{'text': 'One mocha cake, ready.', 'type': 'text'}]

        result = await wait_task(client.session, created)
        print(result.content)
        # [TextContent(text='One mocha cake, ready.')]
