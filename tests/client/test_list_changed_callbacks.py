"""Tests for list_changed notification callbacks in ClientSession."""

import anyio
import pytest

from mcp import types
from mcp.client.session import ClientSession
from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.shared.message import SessionMessage

pytestmark = pytest.mark.anyio


async def test_tool_list_changed_callback():
    """Verify that the client invokes the tool_list_changed callback when
    the server sends a notifications/tools/list_changed notification."""
    callback_called = anyio.Event()

    async def on_tools_changed() -> None:
        callback_called.set()

    async def _list_tools(_ctx: object, _params: object) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[])  # pragma: no cover

    server = Server(
        name="ListChangedServer",
        on_list_tools=_list_tools,
    )

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    async with anyio.create_task_group() as tg:

        async def run_server():
            async with ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="ListChangedServer",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(tools_changed=True), {}),
                ),
            ) as server_session:
                async for message in server_session.incoming_messages:
                    await server._handle_message(message, server_session, {})

        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            tool_list_changed_callback=on_tools_changed,
        ) as session:
            await session.initialize()

            # Have the server send a tool list changed notification directly
            await server_to_client_send.send(
                SessionMessage(
                    message=types.JSONRPCNotification(
                        jsonrpc="2.0",
                        **types.ToolListChangedNotification().model_dump(by_alias=True, mode="json", exclude_none=True),
                    ),
                )
            )

            with anyio.fail_after(2):
                await callback_called.wait()

            tg.cancel_scope.cancel()  # pragma: no cover


async def test_prompt_list_changed_callback():
    """Verify the prompt_list_changed callback is invoked."""
    callback_called = anyio.Event()

    async def on_prompts_changed() -> None:
        callback_called.set()

    server = Server(name="ListChangedServer")

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    async with anyio.create_task_group() as tg:

        async def run_server():
            async with ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="ListChangedServer",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(prompts_changed=True), {}),
                ),
            ) as server_session:
                async for message in server_session.incoming_messages:
                    await server._handle_message(message, server_session, {})

        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            prompt_list_changed_callback=on_prompts_changed,
        ) as session:
            await session.initialize()

            await server_to_client_send.send(
                SessionMessage(
                    message=types.JSONRPCNotification(
                        jsonrpc="2.0",
                        **types.PromptListChangedNotification().model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        ),
                    ),
                )
            )

            with anyio.fail_after(2):
                await callback_called.wait()

            tg.cancel_scope.cancel()  # pragma: no cover


async def test_resource_list_changed_callback():
    """Verify the resource_list_changed callback is invoked."""
    callback_called = anyio.Event()

    async def on_resources_changed() -> None:
        callback_called.set()

    server = Server(name="ListChangedServer")

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    async with anyio.create_task_group() as tg:

        async def run_server():
            async with ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="ListChangedServer",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(resources_changed=True), {}),
                ),
            ) as server_session:
                async for message in server_session.incoming_messages:
                    await server._handle_message(message, server_session, {})

        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            resource_list_changed_callback=on_resources_changed,
        ) as session:
            await session.initialize()

            await server_to_client_send.send(
                SessionMessage(
                    message=types.JSONRPCNotification(
                        jsonrpc="2.0",
                        **types.ResourceListChangedNotification().model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        ),
                    ),
                )
            )

            with anyio.fail_after(2):
                await callback_called.wait()

            tg.cancel_scope.cancel()  # pragma: no cover


async def test_list_changed_default_no_error():
    """Verify that without callbacks, list_changed notifications are handled
    silently (no errors, no hangs)."""
    server = Server(name="ListChangedServer")

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    async with anyio.create_task_group() as tg:

        async def run_server():
            async with ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="ListChangedServer",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session:
                async for message in server_session.incoming_messages:
                    await server._handle_message(message, server_session, {})

        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
        ) as session:
            await session.initialize()

            # Send all three list_changed notifications — none should cause errors
            for notification_cls in (
                types.ToolListChangedNotification,
                types.PromptListChangedNotification,
                types.ResourceListChangedNotification,
            ):
                await server_to_client_send.send(
                    SessionMessage(
                        message=types.JSONRPCNotification(
                            jsonrpc="2.0",
                            **notification_cls().model_dump(by_alias=True, mode="json", exclude_none=True),
                        ),
                    )
                )

            # Give the session a moment to process
            await anyio.sleep(0.1)

            tg.cancel_scope.cancel()  # pragma: no cover


async def test_callback_exception_does_not_crash_session():
    """Verify that an exception in a list_changed callback is logged but does
    not crash the client session."""

    async def bad_callback() -> None:
        raise RuntimeError("boom")

    server = Server(name="ListChangedServer")

    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[SessionMessage](5)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[SessionMessage](5)

    async with anyio.create_task_group() as tg:

        async def run_server():
            async with ServerSession(
                client_to_server_receive,
                server_to_client_send,
                InitializationOptions(
                    server_name="ListChangedServer",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(NotificationOptions(), {}),
                ),
            ) as server_session:
                async for message in server_session.incoming_messages:
                    await server._handle_message(message, server_session, {})

        tg.start_soon(run_server)

        async with ClientSession(
            server_to_client_receive,
            client_to_server_send,
            tool_list_changed_callback=bad_callback,
            prompt_list_changed_callback=bad_callback,
            resource_list_changed_callback=bad_callback,
        ) as session:
            await session.initialize()

            # Send all three notification types — all callbacks will raise,
            # but the session should survive.
            for notification_cls in (
                types.ToolListChangedNotification,
                types.PromptListChangedNotification,
                types.ResourceListChangedNotification,
            ):
                await server_to_client_send.send(
                    SessionMessage(
                        message=types.JSONRPCNotification(
                            jsonrpc="2.0",
                            **notification_cls().model_dump(by_alias=True, mode="json", exclude_none=True),
                        ),
                    )
                )

            # Session should still be alive — verify by waiting for processing
            await anyio.sleep(0.1)

            tg.cancel_scope.cancel()  # pragma: no cover
