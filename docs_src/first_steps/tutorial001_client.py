import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


if __name__ == "__main__":
    anyio.run(main)
