from unittest.mock import AsyncMock, patch
from uuid import uuid4

import anyio
import pytest
from pydantic import ValidationError

import mcp.types as types
from mcp.server.message_queue.redis import RedisMessageDispatch
from mcp.shared.message import SessionMessage

# Set up fakeredis for testing
try:
    from fakeredis import aioredis as fake_redis
except ImportError:
    pytest.skip(
        "fakeredis is required for testing Redis functionality", allow_module_level=True
    )


@pytest.fixture
async def redis_dispatch():
    """Create a Redis message dispatch with a fake Redis client."""
    # Mock the redis module entirely within RedisMessageDispatch
    with patch("mcp.server.message_queue.redis.redis", fake_redis.FakeRedis):
        from mcp.server.message_queue.redis import RedisMessageDispatch

        dispatch = RedisMessageDispatch(session_ttl=5)  # Shorter TTL for testing
        try:
            yield dispatch
        finally:
            await dispatch.close()


@pytest.mark.anyio
async def test_session_exists(redis_dispatch):
    """Test session existence check."""
    session_id = uuid4()

    # Initially session should not exist
    assert not await redis_dispatch.session_exists(session_id)

    # After subscribing, session should exist
    async with redis_dispatch.subscribe(session_id, AsyncMock()):
        assert await redis_dispatch.session_exists(session_id)

    # After unsubscribing, session should not exist
    assert not await redis_dispatch.session_exists(session_id)


@pytest.mark.anyio
async def test_session_ttl(redis_dispatch):
    """Test that session has proper TTL set."""
    session_id = uuid4()

    async with redis_dispatch.subscribe(session_id, AsyncMock()):
        session_key = redis_dispatch._session_key(session_id)
        ttl = await redis_dispatch._redis.ttl(session_key)  # type: ignore
        assert ttl > 0
        assert ttl <= redis_dispatch._session_ttl


@pytest.mark.anyio
async def test_session_heartbeat(redis_dispatch):
    """Test that session heartbeat refreshes TTL."""
    session_id = uuid4()

    async with redis_dispatch.subscribe(session_id, AsyncMock()):
        session_key = redis_dispatch._session_key(session_id)

        # Initial TTL
        initial_ttl = await redis_dispatch._redis.ttl(session_key)  # type: ignore
        assert initial_ttl > 0

        # Wait for heartbeat to run
        await anyio.sleep(redis_dispatch._session_ttl / 2 + 0.5)

        # TTL should be refreshed
        refreshed_ttl = await redis_dispatch._redis.ttl(session_key)  # type: ignore
        assert refreshed_ttl > 0
        assert refreshed_ttl <= redis_dispatch._session_ttl


@pytest.mark.anyio
async def test_subscribe_unsubscribe(redis_dispatch):
    """Test subscribing and unsubscribing from a session."""
    session_id = uuid4()
    callback = AsyncMock()

    # Subscribe
    async with redis_dispatch.subscribe(session_id, callback):
        # Check that session is tracked
        assert session_id in redis_dispatch._session_state
        assert await redis_dispatch.session_exists(session_id)

    # After context exit, session should be cleaned up
    assert session_id not in redis_dispatch._session_state
    assert not await redis_dispatch.session_exists(session_id)


@pytest.mark.anyio
async def test_publish_message_valid_json(redis_dispatch: RedisMessageDispatch):
    """Test publishing a valid JSON-RPC message."""
    session_id = uuid4()
    callback = AsyncMock()
    message = types.JSONRPCMessage.model_validate(
        {"jsonrpc": "2.0", "method": "test", "params": {}, "id": 1}
    )

    # Subscribe to messages
    async with redis_dispatch.subscribe(session_id, callback):
        # Publish message
        published = await redis_dispatch.publish_message(
            session_id, SessionMessage(message=message)
        )
        assert published

        # Give some time for the message to be processed
        await anyio.sleep(0.1)

        # Callback should have been called with the message
        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        assert isinstance(call_args, SessionMessage)
        assert isinstance(call_args.message.root, types.JSONRPCRequest)
        assert (
            call_args.message.root.method == "test"
        )  # Access method through root attribute


@pytest.mark.anyio
async def test_publish_message_invalid_json(redis_dispatch):
    """Test publishing an invalid JSON string."""
    session_id = uuid4()
    callback = AsyncMock()
    invalid_json = '{"invalid": "json",,}'  # Invalid JSON

    # Subscribe to messages
    async with redis_dispatch.subscribe(session_id, callback):
        # Publish invalid message
        published = await redis_dispatch.publish_message(session_id, invalid_json)
        assert published

        # Give some time for the message to be processed
        await anyio.sleep(0.1)

        # Callback should have been called with a ValidationError
        callback.assert_called_once()
        error = callback.call_args[0][0]
        assert isinstance(error, ValidationError)


@pytest.mark.anyio
async def test_publish_to_nonexistent_session(redis_dispatch):
    """Test publishing to a session that doesn't exist."""
    session_id = uuid4()
    message = types.JSONRPCMessage.model_validate(
        {"jsonrpc": "2.0", "method": "test", "params": {}, "id": 1}
    )

    published = await redis_dispatch.publish_message(session_id, message)
    assert not published


@pytest.mark.anyio
async def test_extract_session_id(redis_dispatch):
    """Test extracting session ID from channel name."""
    session_id = uuid4()
    channel = redis_dispatch._session_channel(session_id)

    # Valid channel
    extracted_id = redis_dispatch._extract_session_id(channel)
    assert extracted_id == session_id

    # Invalid channel format
    extracted_id = redis_dispatch._extract_session_id("invalid_channel_name")
    assert extracted_id is None

    # Invalid UUID in channel
    invalid_channel = f"{redis_dispatch._prefix}session:invalid_uuid"
    extracted_id = redis_dispatch._extract_session_id(invalid_channel)
    assert extracted_id is None


@pytest.mark.anyio
async def test_multiple_sessions(redis_dispatch: RedisMessageDispatch):
    """Test handling multiple concurrent sessions."""
    session1 = uuid4()
    session2 = uuid4()
    callback1 = AsyncMock()
    callback2 = AsyncMock()

    async with redis_dispatch.subscribe(session1, callback1):
        async with redis_dispatch.subscribe(session2, callback2):
            # Both sessions should exist
            assert await redis_dispatch.session_exists(session1)
            assert await redis_dispatch.session_exists(session2)

            # Publish to session1
            message1 = types.JSONRPCMessage.model_validate(
                {"jsonrpc": "2.0", "method": "test1", "params": {}, "id": 1}
            )
            await redis_dispatch.publish_message(
                session1, SessionMessage(message=message1)
            )

            # Publish to session2
            message2 = types.JSONRPCMessage.model_validate(
                {"jsonrpc": "2.0", "method": "test2", "params": {}, "id": 2}
            )
            await redis_dispatch.publish_message(
                session2, SessionMessage(message=message2)
            )

            # Give some time for messages to be processed
            await anyio.sleep(0.1)

            # Check callbacks
            callback1.assert_called_once()
            callback2.assert_called_once()

            call1_args = callback1.call_args[0][0]
            assert isinstance(call1_args, SessionMessage)
            assert call1_args.message.root.method == "test1"  # type: ignore

            call2_args = callback2.call_args[0][0]
            assert isinstance(call2_args, SessionMessage)
            assert call2_args.message.root.method == "test2"  # type: ignore


@pytest.mark.anyio
async def test_task_group_cancellation(redis_dispatch):
    """Test that task group is properly cancelled when context exits."""
    session_id = uuid4()
    callback = AsyncMock()

    async with redis_dispatch.subscribe(session_id, callback):
        # Check that task group is active
        _, task_group = redis_dispatch._session_state[session_id]
        assert task_group.cancel_scope.cancel_called is False

    # After context exit, task group should be cancelled
    # And session state should be cleaned up
    assert session_id not in redis_dispatch._session_state


@pytest.mark.anyio
async def test_session_cancellation_isolation(redis_dispatch):
    """Test that cancelling one session doesn't affect other sessions."""
    session1 = uuid4()
    session2 = uuid4()

    # Create a blocking callback for session1 to ensure it's running when cancelled
    session1_event = anyio.Event()
    session1_started = anyio.Event()
    session1_cancelled = False

    async def blocking_callback1(msg):
        session1_started.set()
        try:
            await session1_event.wait()
        except anyio.get_cancelled_exc_class():
            nonlocal session1_cancelled
            session1_cancelled = True
            raise

    callback2 = AsyncMock()

    # Start session2 first
    async with redis_dispatch.subscribe(session2, callback2):
        # Start session1 with a blocking callback
        async with anyio.create_task_group() as tg:

            async def session1_runner():
                async with redis_dispatch.subscribe(session1, blocking_callback1):
                    # Publish a message to trigger the blocking callback
                    message = types.JSONRPCMessage.model_validate(
                        {"jsonrpc": "2.0", "method": "test", "params": {}, "id": 1}
                    )
                    await redis_dispatch.publish_message(session1, message)

                    # Wait for the callback to start
                    await session1_started.wait()

                    # Keep the context alive while we test cancellation
                    await anyio.sleep_forever()

            tg.start_soon(session1_runner)

            # Wait for session1's callback to start
            await session1_started.wait()

            # Cancel session1
            tg.cancel_scope.cancel()

            # Give some time for cancellation to propagate
            await anyio.sleep(0.1)

            # Verify session1 was cancelled
            assert session1_cancelled
            assert session1 not in redis_dispatch._session_state

            # Verify session2 is still active and can receive messages
            assert await redis_dispatch.session_exists(session2)
            message2 = types.JSONRPCMessage.model_validate(
                {"jsonrpc": "2.0", "method": "test2", "params": {}, "id": 2}
            )
            await redis_dispatch.publish_message(session2, message2)

            # Give some time for the message to be processed
            await anyio.sleep(0.1)

            # Verify session2 received the message
            callback2.assert_called_once()
            call_args = callback2.call_args[0][0]
            assert call_args.root.method == "test2"


@pytest.mark.anyio
async def test_listener_task_handoff_on_cancellation(redis_dispatch):
    """
    Test that the single listening task is properly
    handed off when a session is cancelled.
    """
    session1 = uuid4()
    session2 = uuid4()

    session1_messages_received = 0
    session2_messages_received = 0

    async def callback1(msg):
        nonlocal session1_messages_received
        session1_messages_received += 1

    async def callback2(msg):
        nonlocal session2_messages_received
        session2_messages_received += 1

    # Create a cancel scope for session1
    async with anyio.create_task_group() as tg:
        session1_cancel_scope: anyio.CancelScope | None = None

        async def session1_runner():
            nonlocal session1_cancel_scope
            with anyio.CancelScope() as cancel_scope:
                session1_cancel_scope = cancel_scope
                async with redis_dispatch.subscribe(session1, callback1):
                    # Keep session alive until cancelled
                    await anyio.sleep_forever()

        # Start session1
        tg.start_soon(session1_runner)

        # Wait for session1 to be established
        await anyio.sleep(0.1)
        assert session1 in redis_dispatch._session_state

        # Send message to session1 to verify it's working
        message1 = types.JSONRPCMessage.model_validate(
            {"jsonrpc": "2.0", "method": "test1", "params": {}, "id": 1}
        )
        await redis_dispatch.publish_message(session1, message1)
        await anyio.sleep(0.1)
        assert session1_messages_received == 1

        # Start session2 while session1 is still active
        async with redis_dispatch.subscribe(session2, callback2):
            # Both sessions should be active
            assert session1 in redis_dispatch._session_state
            assert session2 in redis_dispatch._session_state

            # Cancel session1
            assert session1_cancel_scope is not None
            session1_cancel_scope.cancel()

            # Wait for cancellation to complete
            await anyio.sleep(0.1)

            # Session1 should be gone, session2 should remain
            assert session1 not in redis_dispatch._session_state
            assert session2 in redis_dispatch._session_state

            # Send message to session2 to verify the listener was handed off
            message2 = types.JSONRPCMessage.model_validate(
                {"jsonrpc": "2.0", "method": "test2", "params": {}, "id": 2}
            )
            await redis_dispatch.publish_message(session2, message2)
            await anyio.sleep(0.1)

            # Session2 should have received the message
            assert session2_messages_received == 1

            # Session1 shouldn't receive any more messages
            assert session1_messages_received == 1

            # Send another message to verify the listener is still working
            message3 = types.JSONRPCMessage.model_validate(
                {"jsonrpc": "2.0", "method": "test3", "params": {}, "id": 3}
            )
            await redis_dispatch.publish_message(session2, message3)
            await anyio.sleep(0.1)

            assert session2_messages_received == 2
