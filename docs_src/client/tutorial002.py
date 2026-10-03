import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        result = await client.list_tools()
        for tool in result.tools:
            print(tool.name)
            print(tool.title)
            print(tool.description)
            print(tool.input_schema)


if __name__ == "__main__":
    anyio.run(main)
