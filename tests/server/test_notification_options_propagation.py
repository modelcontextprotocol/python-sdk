"""Tests for enabling server notifications."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from starlette.applications import Starlette

from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager


@pytest.mark.anyio
async def test_fastmcp_sets_notification_options_affects_initialization():
    """Test that set_notification_options() correctly affects server initialization."""
    server = FastMCP("notification-test")

    # By default there should be no configuration
    assert server._notification_options is None

    # Configure notifications
    server.set_notification_options(
        prompts_changed=True,
        resources_changed=True,
        tools_changed=False,
    )

    # Verify internal NotificationOptions created correctly
    assert isinstance(server._notification_options, NotificationOptions)
    assert server._notification_options.prompts_changed is True
    assert server._notification_options.resources_changed is True
    assert server._notification_options.tools_changed is False


@pytest.mark.anyio
async def test_streamable_http_session_manager_uses_notification_options() -> None:
    # Create the FastMCP server and configure notifications
    server = FastMCP("notification-test")
    server.set_notification_options(
        prompts_changed=True,
        resources_changed=False,
        tools_changed=True,
    )

    # Force creation of the StreamableHTTP session manager without starting uvicorn
    app = server.streamable_http_app()

    assert isinstance(app, Starlette)

    # Get the StreamableHTTPSessionManager
    assert server._session_manager is not None
    session_manager: StreamableHTTPSessionManager = server._session_manager

    # Verify internal NotificationOptions created correctly
    assert isinstance(session_manager._notification_options, NotificationOptions)
    assert session_manager._notification_options.prompts_changed is True
    assert session_manager._notification_options.resources_changed is False
    assert session_manager._notification_options.tools_changed is True


@pytest.mark.anyio
async def test_run_stdio_uses_configured_notification_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify FastMCP passes NotificationOptions to the low-level server.run call."""
    called_with: dict[str, InitializationOptions] = {}

    async def fake_run(
        read_stream: Any,
        write_stream: Any,
        initialization_options: InitializationOptions,
        **kwargs: Any,
    ) -> None:
        """Fake run method capturing the initialization options."""
        called_with["init_opts"] = initialization_options

    # Create the FastMCP server instance
    server = FastMCP("test-server")

    # Patch the low-level server.run method to our fake
    monkeypatch.setattr(server._mcp_server, "run", fake_run)

    # Patch stdio_server to avoid touching real stdin/stdout
    @asynccontextmanager
    async def fake_stdio_server() -> AsyncIterator[tuple[str, str]]:
        yield ("fake_read", "fake_write")

    monkeypatch.setattr("mcp.server.fastmcp.server.stdio_server", fake_stdio_server)

    # Configure notification options
    server.set_notification_options(
        prompts_changed=True,
        resources_changed=True,
        tools_changed=False,
    )

    # Execute run_stdio_async (uses patched run + stdio_server)
    await server.run_stdio_async()

    # Verify our fake_run was actually called
    assert "init_opts" in called_with, "Expected _mcp_server.run to be called with InitializationOptions"

    init_opts: InitializationOptions = called_with["init_opts"]
    assert isinstance(init_opts, InitializationOptions)

    # Verify the NotificationOptions are reflected correctly in capabilities
    caps = init_opts.capabilities
    assert caps.prompts is not None and caps.prompts.listChanged is True
    assert caps.resources is not None and caps.resources.listChanged is True
    assert caps.tools is not None and caps.tools.listChanged is False
