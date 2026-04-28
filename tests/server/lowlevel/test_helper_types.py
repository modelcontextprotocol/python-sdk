"""Test helper_types.py meta field.

These tests verify the changes made to helper_types.py:11 where we added:
    meta: dict[str, Any] | None = field(default=None)

ReadResourceContents is the return type for resource read handlers. It's used internally
by the low-level server to package resource content before sending it over the MCP protocol.
"""

from mcp.server.lowlevel.helper_types import ReadResourceContents


def test_read_resource_contents_with_metadata():
    """Test that ReadResourceContents accepts meta parameter.

    ReadResourceContents is an internal helper type used by the low-level MCP server.
    When a resource is read, the server creates a ReadResourceContents instance that
    contains the content, mime type, and now metadata. The low-level server then
    extracts the meta field and includes it in the protocol response as _meta.
    """
    # Bridge between Resource.meta and MCP protocol _meta field (helper_types.py:11)
    metadata = {"version": "1.0", "cached": True}

    contents = ReadResourceContents(
        content="test content",
        mime_type="text/plain",
        meta=metadata,
    )

    assert contents.meta is not None
    assert contents.meta == metadata
    assert contents.meta["version"] == "1.0"
    assert contents.meta["cached"] is True


def test_read_resource_contents_without_metadata():
    """Test that ReadResourceContents meta defaults to None."""
    # Ensures backward compatibility - meta defaults to None, _meta omitted from protocol (helper_types.py:11)
    contents = ReadResourceContents(
        content="test content",
        mime_type="text/plain",
    )

    assert contents.meta is None


def test_read_resource_contents_with_bytes():
    """Test that ReadResourceContents works with bytes content and meta."""
    # Verifies meta works with both str and bytes content (binary resources like images, PDFs)
    metadata = {"encoding": "utf-8"}

    contents = ReadResourceContents(
        content=b"binary content",
        mime_type="application/octet-stream",
        meta=metadata,
    )

    assert contents.content == b"binary content"
    assert contents.meta == metadata
