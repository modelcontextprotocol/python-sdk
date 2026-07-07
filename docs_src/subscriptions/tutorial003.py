from mcp_types import TextResourceContents

from mcp import Client
from mcp.client.subscriptions import ResourceUpdated, ToolsListChanged

BOARD = "board://sprint"


async def read_board(client: Client, uri: str = BOARD) -> str:
    [contents] = (await client.read_resource(uri)).contents
    assert isinstance(contents, TextResourceContents)
    return contents.text


async def follow_board(client: Client) -> None:
    async with client.listen(tools_list_changed=True, resource_subscriptions=[BOARD]) as sub:
        async for event in sub:
            match event:
                case ResourceUpdated(uri=uri):
                    print(await read_board(client, uri))
                case ToolsListChanged():
                    tools = await client.list_tools()
                    print("tools:", [tool.name for tool in tools.tools])
                case _:
                    pass  # kinds the filter did not ask for never arrive
