from mcp import Client

SERVER_URL = "http://localhost:8000/mcp"


async def main() -> None:
    async with Client(SERVER_URL) as client:
        saved = client.session.discover_result

    async with Client(SERVER_URL, mode="2026-07-28", prior_discover=saved) as client:
        print(client.protocol_version)
        if client.server_info is not None:
            print(client.server_info.name)
