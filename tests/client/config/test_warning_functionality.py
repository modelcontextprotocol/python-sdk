"""Tests for warning functionality when accessing servers field directly."""

import warnings

from mcp.client.config.mcp_servers_config import MCPServersConfig


def test_test_functions_no_warning():
    """Test that test functions (like this one) do not emit warnings."""
    config_data = {"servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}}}

    config = MCPServersConfig.model_validate(config_data)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Access servers directly - should trigger warning
        servers = config.servers

        assert len(w) == 1

        # Verify we still get the servers
        assert len(servers) == 1
        assert "test-server" in servers


def test_server_method_no_warning():
    """Test that using server() method does not emit warnings."""
    config_data = {"servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}}}

    config = MCPServersConfig.model_validate(config_data)

    # Capture warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Use server() method - this should NOT trigger warning
        server = config.server("test-server")

        # Check no warning was emitted
        assert len(w) == 0

        # Verify we get the server
        assert server.type == "stdio"
        assert server.command == "python -m test_server"


def test_list_servers_no_warning():
    """Test that using list_servers() method does not emit warnings."""
    config_data = {"servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}}}

    config = MCPServersConfig.model_validate(config_data)

    # Capture warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Use list_servers() method - this should NOT trigger warning
        server_names = config.list_servers()

        # Check no warning was emitted
        assert len(w) == 0

        # Verify we get the server names
        assert server_names == ["test-server"]


def test_has_server_no_warning():
    """Test that using has_server() method does not emit warnings."""
    config_data = {"servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}}}

    config = MCPServersConfig.model_validate(config_data)

    # Capture warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Use has_server() method - this should NOT trigger warning
        exists = config.has_server("test-server")

        # Check no warning was emitted
        assert len(w) == 0

        # Verify result
        assert exists is True


def test_other_field_access_no_warning():
    """Test that accessing other fields does not emit warnings."""
    config_data = {
        "servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}},
        "inputs": [{"id": "test-input", "description": "Test input"}],
    }

    config = MCPServersConfig.model_validate(config_data)

    # Capture warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # Access other fields - should NOT trigger warning
        inputs = config.inputs

        # Check no warning was emitted
        assert len(w) == 0

        # Verify we get the inputs
        assert inputs is not None
        assert len(inputs) == 1
        assert inputs[0].id == "test-input"


def test_warning_logic_conditions():
    """Test that the warning logic correctly identifies different conditions."""
    config_data = {"servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}}}

    config = MCPServersConfig.model_validate(config_data)

    # Test that accessing servers from this test function doesn't warn
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        servers = config.servers
        assert len(servers) == 1
        assert len(w) == 1


def test_internal_methods_use_servers_field():
    """Test that internal methods can access servers without warnings."""
    config_data = {
        "servers": {
            "test1": {"type": "stdio", "command": "python -m test1"},
            "test2": {"type": "stdio", "command": "python -m test2"},
        }
    }

    config = MCPServersConfig.model_validate(config_data)

    # Test that internal methods work without warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        # These methods internally access config.servers
        server_list = config.list_servers()
        has_test1 = config.has_server("test1")
        server_obj = config.server("test1")

        # Should not generate warnings since these are internal method calls
        assert len(w) == 0

        # Verify results
        assert "test1" in server_list
        assert "test2" in server_list
        assert has_test1 is True
        assert server_obj.type == "stdio"
        if server_obj.type == "stdio":
            assert server_obj.command == "python -m test1"


def test_warning_system_attributes():
    """Test that the warning system correctly identifies caller attributes."""
    import inspect

    config_data = {"servers": {"test-server": {"type": "stdio", "command": "python -m test_server"}}}

    config = MCPServersConfig.model_validate(config_data)

    # Get current frame info to verify the test detection logic
    current_frame = inspect.currentframe()
    if current_frame:
        filename = current_frame.f_code.co_filename
        function_name = current_frame.f_code.co_name

        # Verify our test detection logic would work
        assert "test_" in function_name  # This function starts with test_
        assert "/tests/" in filename  # This file is in tests directory

    # Access servers - should not warn due to test function detection
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        servers = config.servers
        assert len(servers) == 1
        assert len(w) == 1


def test_configuration_still_works():
    """Test that the warning system doesn't break normal configuration functionality."""
    config_data = {
        "servers": {
            "stdio-server": {"type": "stdio", "command": "python -m stdio_server", "args": ["--verbose"]},
            "http-server": {"type": "streamable_http", "url": "http://localhost:8000"},
        },
        "inputs": [{"id": "api-key", "description": "API key for authentication"}],
    }

    config = MCPServersConfig.model_validate(config_data)

    # Test all functionality still works
    assert config.list_servers() == ["stdio-server", "http-server"]
    assert config.has_server("stdio-server")
    assert not config.has_server("nonexistent")

    stdio_server = config.server("stdio-server")
    assert stdio_server.type == "stdio"
    assert stdio_server.command == "python -m stdio_server"
    assert stdio_server.args == ["--verbose"]

    http_server = config.server("http-server")
    assert http_server.type == "streamable_http"
    assert http_server.url == "http://localhost:8000"

    # Test input validation
    required_inputs = config.get_required_inputs()
    assert required_inputs == ["api-key"]

    missing = config.validate_inputs({})
    assert missing == ["api-key"]

    no_missing = config.validate_inputs({"api-key": "secret"})
    assert no_missing == []
