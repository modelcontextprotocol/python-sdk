import logging

import pytest

from mcp.server.mcpserver import MCPServer


@pytest.fixture
def clean_root_logger():
    """Save and restore the root logger's handlers/level around each test.

    `MCPServer` can mutate the root logger via `logging.basicConfig()`, so
    tests that exercise this behavior must not leak handlers into other
    tests (or into pytest's own log capturing, which itself attaches a
    handler to the root logger -- hence comparing against a baseline
    snapshot below, rather than assuming an empty handler list).
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield root
    root.handlers.clear()
    root.handlers.extend(original_handlers)
    root.setLevel(original_level)


class TestConfigureLogging:
    def test_default_does_not_override_existing_handlers(self, clean_root_logger):
        """If an application has already configured the root logger before
        creating an `MCPServer`, the default behavior must not replace it.

        This matches the standard library's own `logging.basicConfig()`
        contract: it is a no-op if the root logger already has handlers.
        """
        baseline = list(clean_root_logger.handlers)
        app_handler = logging.StreamHandler()
        clean_root_logger.addHandler(app_handler)

        MCPServer("test-server")

        assert clean_root_logger.handlers == [*baseline, app_handler]

    def test_configure_logging_false_leaves_root_logger_untouched(self, clean_root_logger):
        """`configure_logging=False` opts a server out of touching the root
        logger entirely, so an application can safely configure its own
        logging before or after constructing the server.

        See: https://github.com/modelcontextprotocol/python-sdk/issues/1656
        """
        baseline = list(clean_root_logger.handlers)

        MCPServer("test-server", configure_logging=False)
        assert clean_root_logger.handlers == baseline

        # The application's own logging setup, performed afterwards, must
        # take effect (i.e. must not have been pre-empted by the server).
        # Clear first so `basicConfig` (a no-op if handlers already exist)
        # is guaranteed to actually apply the new format.
        clean_root_logger.handlers.clear()
        logging.basicConfig(format="MYAPP: %(message)s")
        assert len(clean_root_logger.handlers) == 1
        assert clean_root_logger.handlers[0].formatter._fmt == "MYAPP: %(message)s"
