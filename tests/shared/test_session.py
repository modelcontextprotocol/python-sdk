from collections.abc import AsyncGenerator

import anyio
import pytest

import mcp.types as types
from mcp.client.session import ClientSession
from mcp.server.lowlevel.server import Server
from mcp.shared.exceptions import McpError
from mcp.shared.memory import (
    create_client_server_memory_streams,
    create_connected_server_and_client_session,
)
from mcp.types import (
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
    ClientRequest,
    EmptyResult,
)


@pytest.fixture
def mcp_server() -> Server:
    return Server(name="test server")


@pytest.fixture
async def client_connected_to_server(
    mcp_server: Server,
) -> AsyncGenerator[ClientSession, None]:
    async with create_connected_server_and_client_session(mcp_server) as client_session:
        yield client_session


@pytest.mark.anyio
async def test_in_flight_requests_cleared_after_completion(
    client_connected_to_server: ClientSession,
):
    """Verify that _in_flight is empty after all requests complete."""
    # Send a request and wait for response
    response = await client_connected_to_server.send_ping()
    assert isinstance(response, EmptyResult)

    # Verify _in_flight is empty
    assert len(client_connected_to_server._in_flight) == 0


@pytest.mark.anyio
async def test_request_cancellation():
    """Test that requests can be cancelled while in-flight."""
    # The tool is already registered in the fixture

    ev_tool_called = anyio.Event()
    ev_cancelled = anyio.Event()
    request_id = None

    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal request_id, ev_tool_called
            if name == "slow_tool":
                request_id = server.request_context.request_id
                ev_tool_called.set()
                await anyio.sleep(10)  # Long enough to ensure we can cancel
                return []
            raise ValueError(f"Unknown tool: {name}")

        # Register the tool so it shows up in list_tools
        @server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="slow_tool",
                    description="A slow tool that takes 10 seconds to complete",
                    inputSchema={},
                )
            ]

        return server

    async def make_request(client_session):
        nonlocal ev_cancelled
        try:
            await client_session.send_request(
                ClientRequest(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="slow_tool", arguments={}
                        ),
                    )
                ),
                types.CallToolResult,
            )
            pytest.fail("Request should have been cancelled")
        except McpError as e:
            # Expected - request was cancelled
            assert "Request cancelled" in str(e)
            ev_cancelled.set()

    async with create_connected_server_and_client_session(
        make_server()
    ) as client_session:
        async with anyio.create_task_group() as tg:
            tg.start_soon(make_request, client_session)

            # Wait for the request to be in-flight
            with anyio.fail_after(1):  # Timeout after 1 second
                await ev_tool_called.wait()

            # Send cancellation notification
            assert request_id is not None
            await client_session.send_notification(
                ClientNotification(
                    CancelledNotification(
                        method="notifications/cancelled",
                        params=CancelledNotificationParams(requestId=request_id),
                    )
                )
            )

            # Give cancellation time to process
            with anyio.fail_after(1):
                await ev_cancelled.wait()


@pytest.mark.anyio
async def test_request_async():
    """Test that requests can be run asynchronously."""
    # The tool is already registered in the fixture

    ev_tool_called = anyio.Event()

    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal ev_tool_called
            if name == "async_tool":
                ev_tool_called.set()
                return [types.TextContent(type="text", text="test")]
            raise ValueError(f"Unknown tool: {name}")

        # Register the tool so it shows up in list_tools
        @server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="async_tool",
                    description="A tool that does things asynchronously",
                    inputSchema={},
                    preferAsync=True,
                )
            ]

        return server

    async def make_request(client_session: ClientSession):
        return await client_session.send_request(
            ClientRequest(
                types.CallToolAsyncRequest(
                    method="tools/async/call",
                    params=types.CallToolAsyncRequestParams(
                        name="async_tool", arguments={}
                    ),
                )
            ),
            types.CallToolAsyncResult,
        )

    async def get_result(client_session: ClientSession, async_token: types.AsyncToken):
        with anyio.fail_after(1):
            while True:
                print("getting results")
                result = await client_session.send_request(
                    ClientRequest(
                        types.GetToolAsyncResultRequest(
                            method="tools/async/get",
                            params=types.GetToolAsyncResultRequestParams(
                                token=async_token
                            ),
                        )
                    ),
                    types.CallToolResult,
                )
                print(f"retrieved {result}")
                if result.isPending:
                    await anyio.sleep(1)
                elif result.isError:
                    raise RuntimeError(str(result))
                else:
                    return result

    async with create_connected_server_and_client_session(
        make_server()
    ) as client_session:
        async_call = await make_request(client_session)
        assert async_call is not None
        assert async_call.token is not None
        with anyio.fail_after(1):  # Timeout after 1 second
            await ev_tool_called.wait()
        result = await get_result(client_session, async_call.token)
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "test"

from logging import getLogger

logger = getLogger(__name__)

@pytest.mark.anyio
@pytest.mark.skip(reason="This test does not work, there is a subtle "
                  "bug with event.wait, lower level test_result_cache "
                  "tests underlying behaviour, revisit with feedback " \
                  "from someone who cah help debug")
async def test_request_async_join():
    """Test that requests can be joined from external sessions."""
    # The tool is already registered in the fixture

    # TODO note these events are not working as expected
    # test code below uses move_on_after rather than
    # fail_after as events are not triggered as expected
    # this effectively makes the test lots of sleep
    # calls, needs further investigation
    ev_client_1_started = anyio.Event()
    ev_client_2_joined = anyio.Event()
    ev_client_1_progressed_1 = anyio.Event()
    ev_client_1_progressed_2 = anyio.Event()
    ev_client_2_progressed_1 = anyio.Event()
    ev_done = anyio.Event()


    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal ev_client_2_joined
            if name == "async_tool":
                try:
                    logger.info("tool: sending 1/2")
                    await server.request_context.session.send_progress_notification(
                        progress_token=server.request_context.request_id,
                        progress=1,
                        total=2,
                    )
                    logger.info("tool: sent 1/2")
                    with anyio.fail_after(10):  # Timeout after 1 second
                        # TODO this is not working for some unknown reason
                        logger.info("tool: waiting for client 2 joined")
                        await ev_client_2_joined.wait()

                    logger.info("tool: sending 2/2")
                    await server.request_context.session.send_progress_notification(
                        progress_token=server.request_context.request_id,
                        progress=2,
                        total=2,
                    )
                    logger.info("tool: sent 2/2")
                    result = [types.TextContent(type="text", text="test")]
                    logger.info("tool: sending result")
                    return result
                except Exception as e:
                    logger.exception(e)
                    logger.info(f"tool: caught: {str(e)}")
                    raise e
            else:
                raise ValueError(f"Unknown tool: {name}")

        # Register the tool so it shows up in list_tools
        @server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return [
                types.Tool(
                    name="async_tool",
                    description="A tool that does things asynchronously",
                    inputSchema={},
                    preferAsync=True,
                )
            ]

        return server

    async def client_1_progress_callback(
        progress: float, total: float | None, message: str | None
    ):
        nonlocal ev_client_1_progressed_1
        nonlocal ev_client_1_progressed_2
        logger.info(f"client1: progress started: {progress}/{total}")
        if progress == 1.0:
            ev_client_1_progressed_1.set()
            logger.info("client1: progress 1 set")
        else:
            ev_client_1_progressed_2.set()
            logger.info("client1: progress 2 set")
        logger.info(f"client1: progress done: {progress}/{total}")

    async def make_request(client_session: ClientSession):
        return await client_session.send_request(
            ClientRequest(
                types.CallToolAsyncRequest(
                    method="tools/async/call",
                    params=types.CallToolAsyncRequestParams(
                        name="async_tool",
                        arguments={},
                    ),
                )
            ),
            types.CallToolAsyncResult,
            progress_callback=client_1_progress_callback,
        )

    async def client_2_progress_callback(
        progress: float, total: float | None, message: str | None
    ):
        nonlocal ev_client_2_progressed_1
        logger.info(f"client2: progress started: {progress}/{total}")
        ev_client_2_progressed_1.set()
        logger.info(f"client2: progress done: {progress}/{total}")

    async def join_request(
        client_session: ClientSession, 
        async_token: types.AsyncToken
    ):
        return await client_session.send_request(
            ClientRequest(
                types.JoinCallToolAsyncRequest(
                    method="tools/async/join",
                    params=types.JoinCallToolRequestParams(token=async_token),
                )
            ),
            types.CallToolAsyncResult,
            progress_callback=client_2_progress_callback,
        )

    async def get_result(client_session: ClientSession, async_token: types.AsyncToken):
        while True:
            result = await client_session.send_request(
                ClientRequest(
                    types.GetToolAsyncResultRequest(
                        method="tools/async/get",
                        params=types.GetToolAsyncResultRequestParams(token=async_token),
                    )
                ),
                types.CallToolResult,
            )
            if result.isPending:
                logger.info("client1: result is pending, sleeping")
                await anyio.sleep(1)
            elif result.isError:
                raise RuntimeError(str(result))
            else:
                return result

    server = make_server()
    token = None

    async with anyio.create_task_group() as tg:
        async def client_1_submit():
            async with create_connected_server_and_client_session(
                server
            ) as client_session:
                nonlocal token
                nonlocal ev_client_1_started
                nonlocal ev_client_2_progressed_1
                nonlocal ev_done
                async_call = await make_request(client_session)
                assert async_call is not None
                assert async_call.token is not None
                token = async_call.token
                ev_client_1_started.set()
                logger.info("client1: got token")
                with anyio.fail_after(1):  # Timeout after 1 second
                    logger.info("client1: waiting for client 2 progress")
                    await ev_client_2_progressed_1.wait()

                logger.info("client1: getting result")
                result = await get_result(client_session, token)
                ev_done.set()

                assert type(result.content[0]) is types.TextContent
                assert result.content[0].text == "test"

        async def client_2_join():
            async with create_connected_server_and_client_session(
                server
            ) as client_session:
                nonlocal token
                nonlocal ev_client_1_started
                nonlocal ev_client_1_progressed_1
                nonlocal ev_client_2_joined
                nonlocal ev_done

                with anyio.fail_after(1):  # Timeout after 1 second
                    logger.info("client2: waiting for token")
                    await ev_client_1_started.wait()
                    assert token is not None
                    logger.info("client2: got token")
                    logger.info("client2: waiting for client 1 progress 1")
                    await ev_client_1_progressed_1.wait()

                with anyio.fail_after(1):  # Timeout after 1 second
                    logger.info("client2: joining")
                    join_async = await join_request(client_session, token)
                    assert join_async is not None
                    assert join_async.token is not None
                    ev_client_2_joined.set()
                    ("client2: joined")

                with anyio.fail_after(10):  # Timeout after 1 second
                    logger.info("client2: waiting for done")
                    await ev_done.wait()
                    logger.info("client2: done")

        tg.start_soon(client_1_submit)
        tg.start_soon(client_2_join)

    assert ev_client_1_started.is_set()
    assert ev_client_2_joined.is_set()
    assert ev_client_1_progressed_1.is_set()
    assert ev_client_1_progressed_2.is_set()
    assert ev_client_2_progressed_1.is_set()

@pytest.mark.anyio
async def test_connection_closed():
    """
    Test that pending requests are cancelled when the connection is closed remotely.
    """

    ev_closed = anyio.Event()
    ev_response = anyio.Event()

    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async def make_request(client_session):
            """Send a request in a separate task"""
            nonlocal ev_response
            try:
                # any request will do
                await client_session.initialize()
                pytest.fail("Request should have errored")
            except McpError as e:
                # Expected - request errored
                assert "Connection closed" in str(e)
                ev_response.set()

        async def mock_server():
            """Wait for a request, then close the connection"""
            nonlocal ev_closed
            # Wait for a request
            await server_read.receive()
            # Close the connection, as if the server exited
            server_write.close()
            server_read.close()
            ev_closed.set()

        async with (
            anyio.create_task_group() as tg,
            ClientSession(
                read_stream=client_read,
                write_stream=client_write,
            ) as client_session,
        ):
            tg.start_soon(make_request, client_session)
            tg.start_soon(mock_server)

            with anyio.fail_after(1):
                await ev_closed.wait()
            with anyio.fail_after(1):
                await ev_response.wait()
