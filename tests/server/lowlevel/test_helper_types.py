from mcp.server.lowlevel.helper_types import ReadResourceContents


def test_read_resource_contents_with_metadata():
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
    contents = ReadResourceContents(
        content="test content",
        mime_type="text/plain",
    )

    assert contents.meta is None


def test_read_resource_contents_with_bytes():
    metadata = {"encoding": "utf-8"}

    contents = ReadResourceContents(
        content=b"binary content",
        mime_type="application/octet-stream",
        meta=metadata,
    )

    assert contents.content == b"binary content"
    assert contents.meta == metadata
