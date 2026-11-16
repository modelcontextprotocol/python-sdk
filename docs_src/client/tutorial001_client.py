import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        print(client.server_info)
        print(client.server_capabilities)
        print(client.protocol_version)
        print(client.instructions)


if __name__ == "__main__":
    anyio.run(main)
