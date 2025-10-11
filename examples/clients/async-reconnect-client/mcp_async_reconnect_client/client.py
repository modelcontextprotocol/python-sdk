import logging

import anyio
import click
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.context import RequestContext

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)


async def elicitation_callback(context: RequestContext[ClientSession, None], params: types.ElicitRequestParams):
    """Handle elicitation requests from the server."""
    logger.info(f"Server is asking: {params.message}")
    return types.ElicitResult(
        action="accept",
        content={"continue_processing": True},
    )


async def call_async_tool(session: ClientSession, token: str | None):
    """Demonstrate calling an async tool."""
    if not token:
        logger.info("Calling async tool...")
        result = await session.call_tool(
            "fetch_website",
            arguments={"url": "https://modelcontextprotocol.io"},
        )
        if result.isError:
            raise RuntimeError(f"Error calling tool: {result}")
        assert result.operation
        token = result.operation.token
        logger.info(f"Operation started with token: {token}")

    # Poll for completion
    while True:
        status = await session.get_operation_status(token)
        logger.info(f"Status: {status.status}")

        if status.status == "completed":
            final_result = await session.get_operation_result(token)
            for content in final_result.result.content:
                if isinstance(content, types.TextContent):
                    logger.info(f"Result: {content.text}")
            break
        elif status.status == "failed":
            logger.error(f"Operation failed: {status.error}")
            break

        await anyio.sleep(0.5)


async def run_session(endpoint: str, token: str | None):
    async with streamablehttp_client(endpoint) as (read, write, _):
        async with ClientSession(
            read, write, protocol_version="next", elicitation_callback=elicitation_callback
        ) as session:
            await session.initialize()
            await call_async_tool(session, token)


@click.command()
@click.option("--endpoint", default="http://127.0.0.1:8000/mcp", help="Endpoint to connect to")
@click.option("--token", default=None, help="Operation token to resume with")
def main(endpoint: str, token: str | None):
    anyio.run(run_session, endpoint, token)
