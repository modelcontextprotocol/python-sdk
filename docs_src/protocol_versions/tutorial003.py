import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="2026-07-28") as client:
        print(client.protocol_version)


if __name__ == "__main__":
    anyio.run(main)
