"""The extension-identifier grammar in `mcp.shared.extension`, shared by server and client."""

from typing import Any

import pytest

import mcp.server.extension
import mcp.shared.extension
from mcp.shared.extension import validate_extension_identifier


def test_server_extension_module_reexports_shared_validator() -> None:
    """SDK-defined: `mcp.server.extension` re-exports the shared validator as the same function object."""
    assert mcp.server.extension.validate_extension_identifier is mcp.shared.extension.validate_extension_identifier


@pytest.mark.parametrize(
    "identifier",
    [
        "io.modelcontextprotocol/ui",
        "com.example/my_ext",
        "com.x-y.z2/n.a-b_c",
        "example/x",
        "a/b",
        "com.example/9start",
    ],
)
def test_grammar_conformant_extension_identifiers_are_accepted(identifier: str) -> None:
    """Spec `_meta` key grammar: conformant `vendor-prefix/name` identifiers are accepted."""
    validate_extension_identifier(identifier, owner="T")


@pytest.mark.parametrize(
    "identifier",
    [
        "noprefix",
        "-foo/bar",
        ".leading/x",
        "a..b/x",
        "foo-/x",
        "9foo/x",
        "foo/-bar",
        "foo/bar-",
        "foo/",
        "/bar",
        "foo/ba r",
        "io.modelcontextprotocol/ui\n",
        "",
        None,
        42,
    ],
)
def test_malformed_extension_identifiers_are_rejected(identifier: Any) -> None:
    """Spec `_meta` key grammar: malformed prefixes, malformed names, and non-strings are rejected."""
    with pytest.raises(TypeError):
        validate_extension_identifier(identifier, owner="T")
