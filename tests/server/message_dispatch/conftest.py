"""Shared fixtures for message queue tests."""

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest

from mcp.server.message_queue.redis import RedisMessageDispatch

# Set up fakeredis for testing
try:
    from fakeredis import aioredis as fake_redis
except ImportError:
    pytest.skip(
        "fakeredis is required for testing Redis functionality", allow_module_level=True
    )


@pytest.fixture
async def message_dispatch() -> AsyncGenerator[RedisMessageDispatch, None]:
    """Create a shared Redis message dispatch with a fake Redis client."""
    with patch("mcp.server.message_queue.redis.redis", fake_redis.FakeRedis):
        # Shorter TTL for testing
        message_dispatch = RedisMessageDispatch(session_ttl=5)
        try:
            yield message_dispatch
        finally:
            await message_dispatch.close()
