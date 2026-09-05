import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        print(client.server_capabilities.extensions)
        # {'com.example/stamps': {'sealed': True}}
        result = await client.call_tool("stamp", {"text": "hello"})
        print(result.content)
        # [TextContent(type='text', text='[stamped] hello', annotations=None, meta=None)]


if __name__ == "__main__":
    anyio.run(main)
