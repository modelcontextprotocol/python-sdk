"""Tests for SessionState serialization."""

import pytest

from mcp.shared.session_state import SessionState


def test_session_state_creation():
    """Test that SessionState can be created with all fields."""
    state = SessionState(
        session_id="test-session-123",
        protocol_version="2025-11-25",
        next_request_id=5,
        server_capabilities={"tools": {}, "resources": {}},
        server_info={"name": "test-server", "version": "1.0.0"},
        initialized_sent=True,
    )

    assert state.session_id == "test-session-123"
    assert state.protocol_version == "2025-11-25"
    assert state.next_request_id == 5
    assert state.server_capabilities is not None
    assert state.server_info is not None
    assert state.initialized_sent is True


def test_session_state_defaults():
    """Test that SessionState works with minimal required fields."""
    state = SessionState(
        session_id="test-session-456",
        protocol_version="2025-11-25",
        next_request_id=0,
    )

    assert state.server_capabilities is None
    assert state.server_info is None
    assert state.initialized_sent is False


def test_session_state_json_serialization():
    """Test that SessionState can be serialized to JSON and back."""
    original = SessionState(
        session_id="test-session-789",
        protocol_version="2025-11-25",
        next_request_id=10,
        server_capabilities={"tools": {"listChanged": True}},
        server_info={"name": "test-server", "version": "2.0.0"},
        initialized_sent=True,
    )

    # Serialize to JSON
    json_str = original.model_dump_json()

    # Deserialize from JSON
    restored = SessionState.model_validate_json(json_str)

    # Verify all fields match
    assert restored.session_id == original.session_id
    assert restored.protocol_version == original.protocol_version
    assert restored.next_request_id == original.next_request_id
    assert restored.server_capabilities == original.server_capabilities
    assert restored.server_info == original.server_info
    assert restored.initialized_sent == original.initialized_sent


def test_session_state_dict_serialization():
    """Test that SessionState can be serialized to dict and back."""
    original = SessionState(
        session_id="test-session-dict",
        protocol_version="2025-11-25",
        next_request_id=3,
    )

    # Serialize to dict
    data_dict = original.model_dump()

    # Deserialize from dict
    restored = SessionState.model_validate(data_dict)

    assert restored.session_id == original.session_id
    assert restored.next_request_id == original.next_request_id


def test_session_state_validation():
    """Test that SessionState validates input data."""
    with pytest.raises(ValueError):  # Pydantic validation error
        SessionState(
            session_id="test",
            protocol_version="2025-11-25",
            next_request_id=-1,  # Invalid: must be >= 0
        )
