"""Audio/Image media helper validation (#3656)."""

import pytest

from mcp.server.mcpserver.utilities.types import Audio, Image


class TestAudioDataValidation:
    def test_audio_accepts_empty_bytes_payload(self):
        audio = Audio(data=b"")
        assert audio.data == b""
        assert audio.path is None

    def test_audio_accepts_nonempty_bytes_payload(self):
        audio = Audio(data=b"\x00\x01")
        assert audio.data == b"\x00\x01"

    def test_audio_accepts_path_only(self):
        audio = Audio(path="/tmp/x.wav")
        assert audio.path is not None
        assert audio.data is None

    def test_audio_raises_when_nothing_provided(self):
        with pytest.raises(ValueError):
            Audio()

    def test_audio_raises_when_both_provided(self):
        with pytest.raises(ValueError):
            Audio(path="/tmp/x.wav", data=b"")


class TestImageDataValidation:
    def test_image_accepts_empty_bytes_payload(self):
        image = Image(data=b"")
        assert image.data == b""
        assert image.path is None
