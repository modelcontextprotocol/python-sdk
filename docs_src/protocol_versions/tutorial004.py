import anyio

from mcp import Client


async def main() -> None:
    async with Client("http://localhost:8000/mcp") as client:
        saved = client.session.discover_result

    async with Client("http://localhost:8000/mcp", mode="2026-07-28", prior_discover=saved) as client:
        print(client.protocol_version)
        if client.server_info is not None:
            print(client.server_info.name)


if __name__ == "__main__":
    anyio.run(main)
