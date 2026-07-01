"""`docs/servers/media.md`: every claim the page makes, proved against the real SDK."""

import base64

import pytest
from mcp_types import AudioContent, Icon, ImageContent

from docs_src.media import tutorial001, tutorial002, tutorial003
from mcp import Client
from mcp.server.mcpserver import Audio, Image

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_image_return_becomes_an_image_content_block() -> None:
    """tutorial001: `-> Image` reaches the client as a base64 `ImageContent` block, not text."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("logo", {})
        assert not result.is_error
        assert result.content == [
            ImageContent(type="image", data=base64.b64encode(tutorial001.LOGO_PNG).decode(), mime_type="image/png")
        ]


async def test_image_result_has_no_structured_content_and_no_output_schema() -> None:
    """tutorial001: media is content for the model, not data for the application."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema is None
        result = await client.call_tool("logo", {})
        assert result.structured_content is None


async def test_audio_return_becomes_an_audio_content_block() -> None:
    """tutorial002: `Audio` is the same shape as `Image`."""
    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("chime", {})
        assert not result.is_error
        assert result.content == [
            AudioContent(type="audio", data=base64.b64encode(tutorial002.CHIME_WAV).decode(), mime_type="audio/wav")
        ]
        assert result.structured_content is None


def test_raw_data_without_a_format_falls_back_to_a_default_mime_type() -> None:
    """The `!!! check`: with `data=` there is no suffix to guess from, so `format=` decides."""
    assert Image(data=b"\x89PNG\r\n\x1a\n", format="png").to_image_content().mime_type == "image/png"
    assert Image(data=b"\x89PNG\r\n\x1a\n").to_image_content().mime_type == "image/png"
    assert Audio(data=b"\xff\xfb").to_audio_content().mime_type == "audio/wav"


async def test_icons_are_visible_where_they_were_declared() -> None:
    """tutorial003: server icons land on `server_info`, tool icons on the `Tool`, resource icons on the `Resource`."""
    async with Client(tutorial003.mcp) as client:
        assert client.server_info.icons == [
            Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])
        ]
        (tool,) = (await client.list_tools()).tools
        assert tool.icons == [Icon(src="https://example.com/palette.svg", mime_type="image/svg+xml", sizes=["any"])]
        (resource,) = (await client.list_resources()).resources
        assert resource.icons == [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
