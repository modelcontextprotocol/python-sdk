from unittest.mock import patch

from mcp.server.mcpserver import MCPServer


class TestConfigureLogging:
    def test_default_calls_configure_logging(self):
        """By default, `MCPServer` configures logging on construction (the
        pre-existing behavior, preserved for backwards compatibility)."""
        with patch("mcp.server.mcpserver.server._configure_logging") as spy:
            MCPServer("test-server")

        spy.assert_called_once_with("INFO")

    def test_configure_logging_false_skips_configuration(self):
        """`configure_logging=False` opts a server out of calling
        `_configure_logging` (and therefore `logging.basicConfig()`)
        entirely, so an application can safely manage its own logging
        setup without the server racing to configure the root logger
        first.

        See: https://github.com/modelcontextprotocol/python-sdk/issues/1656
        """
        with patch("mcp.server.mcpserver.server._configure_logging") as spy:
            MCPServer("test-server", configure_logging=False)

        spy.assert_not_called()

    def test_configure_logging_true_still_calls_configure_logging(self):
        """Explicitly passing `configure_logging=True` behaves the same as
        the default (sanity check for the new parameter's positive case)."""
        with patch("mcp.server.mcpserver.server._configure_logging") as spy:
            MCPServer("test-server", configure_logging=True, log_level="DEBUG")

        spy.assert_called_once_with("DEBUG")