import codecs
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest
from pydantic import ValidationError

from mcp.server.mcpserver.resources import FileResource


@pytest.fixture
def temp_file():
    """Create a temporary file for testing.

    File is automatically cleaned up after the test if it still exists.
    """
    content = "test content"
    with NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
        f.write(content)
        path = Path(f.name).resolve()
    yield path
    try:  # pragma: lax no cover
        path.unlink()
    except FileNotFoundError:  # pragma: lax no cover
        pass  # File was already deleted by the test


def test_file_resource_creation(temp_file: Path):
    resource = FileResource(
        uri=temp_file.as_uri(),
        name="test",
        description="test file",
        path=temp_file,
    )
    assert str(resource.uri) == temp_file.as_uri()
    assert resource.name == "test"
    assert resource.description == "test file"
    assert resource.mime_type == "text/plain"
    assert resource.path == temp_file
    assert resource.encoding == "utf-8-sig"


def test_file_resource_str_path_conversion(temp_file: Path):
    resource = FileResource(
        uri=f"file://{temp_file}",
        name="test",
        path=Path(str(temp_file)),
    )
    assert isinstance(resource.path, Path)
    assert resource.path.is_absolute()


@pytest.mark.anyio
async def test_read_text_file(temp_file: Path):
    resource = FileResource(
        uri=f"file://{temp_file}",
        name="test",
        path=temp_file,
    )
    content = await resource.read()
    assert content == "test content"
    assert resource.mime_type == "text/plain"


@pytest.mark.anyio
async def test_encoding_none_reads_bytes(temp_file: Path):
    resource = FileResource(
        uri=f"file://{temp_file}",
        name="test",
        path=temp_file,
        encoding=None,
    )
    content = await resource.read()
    assert isinstance(content, bytes)
    assert content == b"test content"


@pytest.mark.parametrize(
    "mime_type",
    [
        "text/plain",
        "text/html",
        "application/json",
        "application/xml",
        "application/vnd.api+json",
        "image/svg+xml",
    ],
)
def test_textual_mime_types_default_to_utf8_sig(temp_file: Path, mime_type: str):
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type=mime_type)
    assert resource.encoding == "utf-8-sig"


@pytest.mark.parametrize("mime_type", ["image/png", "application/octet-stream", "application/pdf"])
def test_binary_mime_types_default_to_no_encoding(temp_file: Path, mime_type: str):
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type=mime_type)
    assert resource.encoding is None


@pytest.mark.parametrize(
    "mime_type",
    ["text/plain; charset=iso-8859-1", 'text/plain; format=flowed; charset="iso-8859-1"'],
)
def test_declared_charset_becomes_default_encoding(temp_file: Path, mime_type: str):
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type=mime_type)
    assert resource.encoding == "iso-8859-1"


def test_removed_is_binary_kwarg_is_rejected(temp_file: Path):
    """The v1 `is_binary` parameter fails loudly at construction rather than being ignored."""
    with pytest.raises(ValidationError, match="is_binary"):
        FileResource.model_validate({"uri": temp_file.as_uri(), "path": temp_file, "is_binary": True})


def test_unknown_encoding_is_rejected(temp_file: Path):
    """A codec typo fails at construction rather than on the first read."""
    with pytest.raises(ValidationError, match="unknown encoding: not-a-codec"):
        FileResource(uri=temp_file.as_uri(), path=temp_file, encoding="not-a-codec")


def test_unknown_declared_charset_is_rejected(temp_file: Path):
    with pytest.raises(ValidationError, match="unknown encoding"):
        FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type="text/plain; charset=not-a-codec")


def test_multibyte_encoding_is_accepted(temp_file: Path):
    """UTF-16 can't decode a lone probe byte but is still a valid text encoding."""
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, encoding="utf-16")
    assert resource.encoding == "utf-16"


def test_non_text_codec_is_rejected(temp_file: Path):
    """A registered codec that isn't a text encoding (bytes-to-bytes) is not a usable encoding."""
    with pytest.raises(ValidationError, match="not a text encoding"):
        FileResource(uri=temp_file.as_uri(), path=temp_file, encoding="base64_codec")


@pytest.mark.anyio
async def test_json_file_is_served_as_text_by_default(temp_file: Path):
    """The mime type that motivated the encoding field: JSON must not become a base64 blob."""
    temp_file.write_text('{"a": 1}', encoding="utf-8")
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type="application/json")
    assert await resource.read() == '{"a": 1}'


@pytest.mark.anyio
async def test_utf8_bom_is_stripped_by_default(temp_file: Path):
    """The default utf-8-sig decoding drops a byte-order mark that would otherwise break JSON parsers."""
    temp_file.write_bytes(codecs.BOM_UTF8 + b'{"a": 1}')
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type="application/json")
    assert await resource.read() == '{"a": 1}'


@pytest.mark.anyio
async def test_explicit_encoding_overrides_default(temp_file: Path):
    """An explicit encoding wins over the mime-type default and is what decodes the file."""
    temp_file.write_bytes("naïve".encode("latin-1"))
    resource = FileResource(uri=temp_file.as_uri(), path=temp_file, mime_type="image/png", encoding="latin-1")
    assert resource.encoding == "latin-1"
    assert await resource.read() == "naïve"


def test_relative_path_error():
    with pytest.raises(ValueError, match="Path must be absolute"):
        FileResource(
            uri="file:///test.txt",
            name="test",
            path=Path("test.txt"),
        )


@pytest.mark.anyio
async def test_missing_file_error(temp_file: Path):
    missing = temp_file.parent / "missing.txt"
    resource = FileResource(
        uri="file:///missing.txt",
        name="test",
        path=missing,
    )
    with pytest.raises(ValueError, match="Error reading file"):
        await resource.read()


@pytest.mark.skipif(os.name == "nt", reason="File permissions behave differently on Windows")
@pytest.mark.anyio
async def test_permission_error(temp_file: Path):  # pragma: lax no cover
    temp_file.chmod(0o000)  # Remove all permissions
    try:
        resource = FileResource(
            uri=temp_file.as_uri(),
            name="test",
            path=temp_file,
        )
        with pytest.raises(ValueError, match="Error reading file"):
            await resource.read()
    finally:
        temp_file.chmod(0o644)  # Restore permissions
