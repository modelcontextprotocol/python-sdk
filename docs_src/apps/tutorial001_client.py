import anyio

from mcp import Client
from mcp.client import advertise
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
from mcp.types import TextContent

APPS_SUPPORT = advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})


async def main() -> None:
    async with Client("http://localhost:8000/mcp", extensions=[APPS_SUPPORT]) as client:
        result = await client.call_tool("get_time", {})
        for block in result.content:
            if isinstance(block, TextContent):
                print(block.text)


if __name__ == "__main__":
    anyio.run(main)
