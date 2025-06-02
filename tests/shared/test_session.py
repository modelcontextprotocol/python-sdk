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
                    print("wibble")
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


@pytest.mark.anyio
async def test_request_async_join():
    """Test that requests can be run asynchronously."""
    # The tool is already registered in the fixture

    # TODO note these events are not working as expected
    # test code below uses move_on_after rather than
    # fail_after as events are not triggered as expected
    # this effectively makes the test lots of sleep
    # calls, needs further investigation
    ev_client_1_started = anyio.Event()
    ev_client2_joined = anyio.Event()
    ev_client1_progressed_1 = anyio.Event()
    ev_client1_progressed_2 = anyio.Event()
    ev_client2_progressed_1 = anyio.Event()
    ev_done = anyio.Event()

    # Start the request in a separate task so we can cancel it
    def make_server() -> Server:
        server = Server(name="TestSessionServer")

        # Register the tool handler
        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict | None) -> list:
            nonlocal ev_client2_joined
            if name == "async_tool":
                try:
                    print("sending 1/2")
                    await server.request_context.session.send_progress_notification(
                        progress_token=server.request_context.request_id,
                        progress=1,
                        total=2,
                    )
                    print("sent 1/2")
                    with anyio.move_on_after(10):  # Timeout after 1 second
                        # TODO this is not working for some unknown reason
                        print("waiting for client 2 joined")
                        await ev_client2_joined.wait()
                        # await anyio.sleep(1)

                    print("sending 2/2")
                    await server.request_context.session.send_progress_notification(
                        progress_token=server.request_context.request_id,
                        progress=2,
                        total=2,
                    )
                    print("sent 2/2")
                    result = [types.TextContent(type="text", text="test")]
                    print("sending result")
                    return result
                except Exception as e:
                    print(f"Caught: {str(e)}")
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

    async def progress_callback_initial(
        progress: float, total: float | None, message: str | None
    ):
        nonlocal ev_client1_progressed_1
        nonlocal ev_client1_progressed_2
        print(f"progress initial started: {progress}/{total}")
        if progress == 1.0:
            ev_client1_progressed_1.set()
            print("progress 1 set")
        else:
            ev_client1_progressed_2.set()
            print("progress 1 set")
        print(f"progress initial done: {progress}/{total}")

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
            progress_callback=progress_callback_initial,
        )

    async def progress_callback_joined(
        progress: float, total: float | None, message: str | None
    ):
        nonlocal ev_client2_progressed_1
        print(f"progress joined started: {progress}/{total}")
        ev_client2_progressed_1.set()
        print(f"progress joined done: {progress}/{total}")

    async def join_request(
        client_session: ClientSession, async_token: types.AsyncToken
    ):
        return await client_session.send_request(
            ClientRequest(
                types.JoinCallToolAsyncRequest(
                    method="tools/async/join",
                    params=types.JoinCallToolRequestParams(token=async_token),
                )
            ),
            types.CallToolAsyncResult,
            progress_callback=progress_callback_joined,
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
                print("Result is pending, sleeping")
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
                nonlocal ev_client2_progressed_1
                nonlocal ev_done
                async_call = await make_request(client_session)
                assert async_call is not None
                assert async_call.token is not None
                token = async_call.token
                ev_client_1_started.set()
                print("Got token")
                with anyio.move_on_after(1):  # Timeout after 1 second
                    print("waiting for client 2 progress")
                    await ev_client2_progressed_1.wait()

                print("Getting result")
                result = await get_result(client_session, token)
                assert type(result.content[0]) is types.TextContent
                assert result.content[0].text == "test"
                ev_done.set()

        async def client_2_join():
            async with create_connected_server_and_client_session(
                server
            ) as client_session:
                nonlocal token
                nonlocal ev_client_1_started
                nonlocal ev_client1_progressed_1
                nonlocal ev_client2_joined
                nonlocal ev_done

                with anyio.move_on_after(1):  # Timeout after 1 second
                    print("waiting for token")
                    await ev_client_1_started.wait()
                    print("waiting for progress 1")
                    await ev_client1_progressed_1.wait()

                with anyio.move_on_after(1):  # Timeout after 1 second
                    assert token is not None
                    print("joining")
                    join_async = await join_request(client_session, token)
                    assert join_async is not None
                    assert join_async.token is not None
                    print("joined")
                    ev_client2_joined.set()
                    print("client 2 joined")

                with anyio.move_on_after(1):  # Timeout after 1 second
                    print("client 2 waiting for done")
                    await ev_done.wait()
                    print("client 2 done")

        tg.start_soon(client_1_submit)
        tg.start_soon(client_2_join)


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
