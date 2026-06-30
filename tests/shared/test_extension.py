"""Tests for `mcp.shared.extension` — the extension-identifier grammar shared by
the server and client extension surfaces.

The grammar matrix (accepted and rejected identifiers) lives with the original
server tests in `tests/server/mcpserver/test_extension.py`, which exercise the
same function via the server module's re-export.
"""

import pytest

import mcp.server.extension
import mcp.shared.extension


def test_validator_importable_from_shared_home() -> None:
    """SDK-defined: the identifier grammar lives in `mcp.shared.extension` — one
    source of truth for both the server and client extension surfaces."""
    mcp.shared.extension.validate_extension_identifier("com.example/thing", owner="T")


def test_validator_rejects_malformed_identifier_via_shared_path() -> None:
    """SDK-defined: the shared-home function enforces the same `vendor-prefix/name`
    grammar the server side always has."""
    with pytest.raises(TypeError):
        mcp.shared.extension.validate_extension_identifier("noprefix", owner="T")


def test_server_extension_module_reexports_shared_validator() -> None:
    """SDK-defined: `mcp.server.extension.validate_extension_identifier` remains
    importable after the move and is the very same function object."""
    assert mcp.server.extension.validate_extension_identifier is mcp.shared.extension.validate_extension_identifier
