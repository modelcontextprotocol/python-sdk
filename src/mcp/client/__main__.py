import argparse
import logging
import sys
from functools import partial
from urllib.parse import urlparse

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.session import RequestResponder
from mcp.types import JSONRPCMessage

if not sys.warnoptions:
    import warnings

    warnings.simplefilter("ignore")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("client")


async def message_handler(
    message: RequestResponder[types.ServerRequest, types.ClientResult]
    | types.ServerNotification
    | Exception,
) -> None:
    if isinstance(message, Exception):
        logger.error("Error: %s", message)
        return

    logger.info("Received message from server: %s", message)


async def run_session(
    read_stream: MemoryObjectReceiveStream[JSONRPCMessage | Exception],
    write_stream: MemoryObjectSendStream[JSONRPCMessage],
    client_info: types.Implementation | None = None,
):
    async with ClientSession(
        read_stream,
        write_stream,
        message_handler=message_handler,
        client_info=client_info,
    ) as session:
        logger.info("Initializing session")
        await session.initialize()
        logger.info("Initialized")


async def main(
    command_or_url: str,
    args: list[str],
    env: list[tuple[str, str]],
    verify_ssl: bool,
):
    env_dict = dict(env)

    if urlparse(command_or_url).scheme in ("http", "https"):
        # Use SSE client for HTTP(S) URLs
        async with sse_client(command_or_url, verify_ssl=verify_ssl) as streams:
            await run_session(*streams)
    else:
        # Use stdio client for commands
        server_parameters = StdioServerParameters(
            command=command_or_url, args=args, env=env_dict
        )
        async with stdio_client(server_parameters) as streams:
            await run_session(*streams)


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("command_or_url", help="Command or URL to connect to")
    parser.add_argument("args", nargs="*", help="Additional arguments")
    parser.add_argument(
        "-e",
        "--env",
        nargs=2,
        action="append",
        metavar=("KEY", "VALUE"),
        help="Environment variables to set. Can be used multiple times.",
        default=[],
    )
    parser.add_argument(
        "--disable-ssl-verification",
        action='store_true',
        default=False,
        help="Disable SSL verification on HTTPS. SSL verification by default.",
    )

    args = parser.parse_args()
    anyio.run(
        partial(
            main,
            args.command_or_url,
            args.args,
            args.env,
            not args.disable_ssl_verification,
        ),
        backend="trio",
    )


if __name__ == "__main__":
    cli()
