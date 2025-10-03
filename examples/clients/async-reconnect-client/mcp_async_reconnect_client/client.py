import anyio
import click
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client


async def call_async_tool(session: ClientSession, token: str | None):
    """Demonstrate calling an async tool."""
    print("Calling async tool...")

    if not token:
        result = await session.call_tool("fetch_website", arguments={"url": "https://modelcontextprotocol.io"})
        assert result.operation
        token = result.operation.token
        print(f"Operation started with token: {token}")

    # Poll for completion
    while True:
        status = await session.get_operation_status(token)
        print(f"Status: {status.status}")

        if status.status == "completed":
            final_result = await session.get_operation_result(token)
            for content in final_result.result.content:
                if isinstance(content, types.TextContent):
                    print(f"Result: {content.text}")
            break
        elif status.status == "failed":
            print(f"Operation failed: {status.error}")
            break

        await anyio.sleep(0.5)


async def run_session(endpoint: str, token: str | None):
    async with streamablehttp_client(endpoint) as (read, write, _):
        async with ClientSession(read, write, protocol_version="next") as session:
            await session.initialize()
            await call_async_tool(session, token)


@click.command()
@click.option("--endpoint", default="http://127.0.0.1:8000/mcp", help="Endpoint to connect to")
@click.option("--token", default=None, help="Operation token to resume with")
def main(endpoint: str, token: str | None):
    anyio.run(run_session, endpoint, token)
