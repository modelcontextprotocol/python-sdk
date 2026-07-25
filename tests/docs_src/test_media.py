"""`docs/servers/media.md`: every claim the page makes, proved against the real SDK."""

import base64
from pathlib import Path

import pytest
from mcp_types import AudioContent, Icon, ImageContent

from docs_src.media import tutorial001, tutorial002, tutorial003, tutorial004
from mcp import Client
from mcp.server.mcpserver import Audio, Image

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


@pytest.fixture
def logo_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The PNG the tutorials expect next to `server.py`, fabricated on disk.

    The SDK never parses the contents, so opaque bytes suffice.
    """
    path = tmp_path / "logo.png"
    path.write_bytes(b"fake png data")
    monkeypatch.setattr(tutorial001, "LOGO_FILE", path)
    monkeypatch.setattr(tutorial002, "LOGO_FILE", path)
    monkeypatch.setattr(tutorial003, "LOGO_FILE", path)
    return path


async def test_image_return_becomes_an_image_content_block(logo_file: Path) -> None:
    """tutorial001: `-> Image` reaches the client as a base64 `ImageContent` block, not text,
    with the MIME type guessed from the `.png` suffix."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("logo", {})
        assert not result.is_error
        assert result.content == [
            ImageContent(type="image", data=base64.b64encode(logo_file.read_bytes()).decode(), mime_type="image/png")
        ]


@pytest.mark.usefixtures("logo_file")
async def test_image_result_has_no_structured_content_and_no_output_schema() -> None:
    """tutorial001: media is content for the model, not data for the application."""
    async with Client(tutorial001.mcp) as client:
        (tool,) = (await client.list_tools()).tools
        assert tool.output_schema is None
        result = await client.call_tool("logo", {})
        assert result.structured_content is None


async def test_audio_return_becomes_an_audio_content_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """tutorial002: `Audio` is the same shape as `Image`."""
    chime_file = tmp_path / "chime.wav"
    chime_file.write_bytes(b"fake wav data")
    monkeypatch.setattr(tutorial002, "CHIME_FILE", chime_file)

    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("chime", {})
        assert not result.is_error
        assert result.content == [
            AudioContent(type="audio", data=base64.b64encode(chime_file.read_bytes()).decode(), mime_type="audio/wav")
        ]
        assert result.structured_content is None


async def test_in_memory_bytes_with_a_format_become_the_same_image_content_block(logo_file: Path) -> None:
    """tutorial003: `data=` plus `format=` produces the same wire block as `path=`."""
    async with Client(tutorial003.mcp) as client:
        result = await client.call_tool("logo_from_bytes", {})
        assert not result.is_error
        assert result.content == [
            ImageContent(type="image", data=base64.b64encode(logo_file.read_bytes()).decode(), mime_type="image/png")
        ]


def test_path_file_is_read_when_the_result_is_built() -> None:
    """The page's `path=` claim (SDK-defined): the file is opened when the result is built,
    not when the helper is constructed — `server.py` can name a file that appears later."""
    image = Image(path="does-not-exist.png")
    with pytest.raises(FileNotFoundError):
        image.to_image_content()


def test_raw_data_without_a_format_falls_back_to_a_default_mime_type() -> None:
    """The `!!! check`: with `data=` there is no suffix to guess from, so `format=` decides."""
    assert Image(data=b"\x89PNG\r\n\x1a\n", format="png").to_image_content().mime_type == "image/png"
    assert Image(data=b"\x89PNG\r\n\x1a\n").to_image_content().mime_type == "image/png"
    assert Audio(data=b"\xff\xfb", format="wav").to_audio_content().mime_type == "audio/wav"
    assert Audio(data=b"\xff\xfb").to_audio_content().mime_type == "audio/wav"


async def test_icons_are_visible_where_they_were_declared() -> None:
    """tutorial004: server icons land on `server_info`, tool icons on the `Tool`, resource icons on the `Resource`."""
    async with Client(tutorial004.mcp) as client:
        assert client.server_info is not None
        assert client.server_info.icons == [
            Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])
        ]
        (tool,) = (await client.list_tools()).tools
        assert tool.icons == [Icon(src="https://example.com/palette.svg", mime_type="image/svg+xml", sizes=["any"])]
        (resource,) = (await client.list_resources()).resources
        assert resource.icons == [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
