"""Tests for public handler registration/deregistration API on low-level Server."""

import pytest

from mcp.server.lowlevel.server import Server


@pytest.fixture
def server():
    return Server(name="test-server")


async def _dummy_request_handler(ctx, params):
    return {"result": "ok"}


async def _dummy_notification_handler(ctx, params):
    pass


class TestAddRequestHandler:
    def test_add_request_handler(self, server):
        server.add_request_handler("custom/method", _dummy_request_handler)
        assert server.has_handler("custom/method")

    def test_add_request_handler_replaces_existing(self, server):
        async def handler_a(ctx, params):
            return "a"

        async def handler_b(ctx, params):
            return "b"

        server.add_request_handler("custom/method", handler_a)
        server.add_request_handler("custom/method", handler_b)
        # The second handler should replace the first
        assert server._request_handlers["custom/method"] is handler_b


class TestRemoveRequestHandler:
    def test_remove_request_handler(self, server):
        server.add_request_handler("custom/method", _dummy_request_handler)
        assert server.has_handler("custom/method")
        server.remove_request_handler("custom/method")
        assert not server.has_handler("custom/method")

    def test_remove_request_handler_not_found(self, server):
        with pytest.raises(KeyError):
            server.remove_request_handler("nonexistent/method")


class TestAddNotificationHandler:
    def test_add_notification_handler(self, server):
        server.add_notification_handler("custom/notify", _dummy_notification_handler)
        assert server.has_handler("custom/notify")

    def test_add_notification_handler_replaces_existing(self, server):
        async def handler_a(ctx, params):
            pass

        async def handler_b(ctx, params):
            pass

        server.add_notification_handler("custom/notify", handler_a)
        server.add_notification_handler("custom/notify", handler_b)
        assert server._notification_handlers["custom/notify"] is handler_b


class TestRemoveNotificationHandler:
    def test_remove_notification_handler(self, server):
        server.add_notification_handler("custom/notify", _dummy_notification_handler)
        assert server.has_handler("custom/notify")
        server.remove_notification_handler("custom/notify")
        assert not server.has_handler("custom/notify")

    def test_remove_notification_handler_not_found(self, server):
        with pytest.raises(KeyError):
            server.remove_notification_handler("nonexistent/notify")


class TestHasHandler:
    def test_has_handler_request(self, server):
        server.add_request_handler("custom/method", _dummy_request_handler)
        assert server.has_handler("custom/method")

    def test_has_handler_notification(self, server):
        server.add_notification_handler("custom/notify", _dummy_notification_handler)
        assert server.has_handler("custom/notify")

    def test_has_handler_unregistered(self, server):
        assert not server.has_handler("nonexistent/method")

    def test_has_handler_default_ping(self, server):
        """The ping handler is registered by default."""
        assert server.has_handler("ping")
