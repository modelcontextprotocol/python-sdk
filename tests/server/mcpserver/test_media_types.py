from pathlib import Path

import pytest

from mcp.server.mcpserver import Audio, Image


@pytest.mark.parametrize(
    ("format_val", "expected_mime"),
    [
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
        ("png", "image/png"),
        ("gif", "image/gif"),
        ("webp", "image/webp"),
        ("bmp", "image/bmp"),
        (".jpg", "image/jpeg"),
        ("JPG", "image/jpeg"),
    ],
)
def test_image_format_mime_types(format_val: str, expected_mime: str) -> None:
    img = Image(data=b"\x00", format=format_val)
    assert img.to_image_content().mime_type == expected_mime


@pytest.mark.parametrize(
    ("filename", "expected_mime"),
    [
        ("chart.jpg", "image/jpeg"),
        ("chart.jpeg", "image/jpeg"),
        ("chart.png", "image/png"),
        ("chart.gif", "image/gif"),
        ("chart.webp", "image/webp"),
        ("chart.unknown", "application/octet-stream"),
    ],
)
def test_image_path_mime_types(filename: str, expected_mime: str, tmp_path: Path) -> None:
    file_path = tmp_path / filename
    file_path.write_bytes(b"\x00")
    img = Image(path=file_path)
    assert img.to_image_content().mime_type == expected_mime


def test_image_raw_data_default_mime_type() -> None:
    img = Image(data=b"\x00")
    assert img.to_image_content().mime_type == "image/png"


@pytest.mark.parametrize(
    ("format_val", "expected_mime"),
    [
        ("mp3", "audio/mpeg"),
        ("m4a", "audio/mp4"),
        ("wav", "audio/wav"),
        ("ogg", "audio/ogg"),
        ("flac", "audio/flac"),
        ("aac", "audio/aac"),
        ("opus", "audio/opus"),
        (".mp3", "audio/mpeg"),
        ("MP3", "audio/mpeg"),
    ],
)
def test_audio_format_mime_types(format_val: str, expected_mime: str) -> None:
    audio = Audio(data=b"\x00", format=format_val)
    assert audio.to_audio_content().mime_type == expected_mime


@pytest.mark.parametrize(
    ("filename", "expected_mime"),
    [
        ("chime.mp3", "audio/mpeg"),
        ("chime.m4a", "audio/mp4"),
        ("chime.wav", "audio/wav"),
        ("chime.ogg", "audio/ogg"),
        ("chime.flac", "audio/flac"),
        ("chime.aac", "audio/aac"),
        ("chime.unknown", "application/octet-stream"),
    ],
)
def test_audio_path_mime_types(filename: str, expected_mime: str, tmp_path: Path) -> None:
    file_path = tmp_path / filename
    file_path.write_bytes(b"\x00")
    audio = Audio(path=file_path)
    assert audio.to_audio_content().mime_type == expected_mime


def test_audio_raw_data_default_mime_type() -> None:
    audio = Audio(data=b"\x00")
    assert audio.to_audio_content().mime_type == "audio/wav"
