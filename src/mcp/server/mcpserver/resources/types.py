"""Concrete resource implementations."""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import httpx2
import pydantic
import pydantic_core
from mcp_types import Annotations, Icon, InputRequiredResult
from pydantic import Field, validate_call

from mcp.server.mcpserver.resources.base import Resource
from mcp.shared._callable_inspection import is_async_callable

# `application/*` types that are textual but predate the `+json`/`+xml`
# structured-syntax suffixes, so the suffix rule below can't catch them.
_TEXTUAL_APPLICATION_TYPES = frozenset({"application/json", "application/xml"})


def _default_file_encoding(mime_type: str) -> str | None:
    """The encoding a file of this mime type is decoded with by default.

    A declared `charset=` parameter wins. Otherwise textual types (`text/*`, JSON,
    XML) are `utf-8-sig` — UTF-8 that also tolerates a byte-order mark — and
    everything else is bytes (None).
    """
    essence, *params = (part.strip() for part in mime_type.split(";"))
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() == "charset" and value:
            return value.strip().strip('"')
    essence = essence.lower()
    if essence.startswith("text/") or essence.endswith(("+json", "+xml")) or essence in _TEXTUAL_APPLICATION_TYPES:
        return "utf-8-sig"
    return None


class TextResource(Resource):
    """A resource that reads from a string."""

    text: str = Field(description="Text content of the resource")

    async def read(self) -> str:
        """Read the text content."""
        return self.text


class BinaryResource(Resource):
    """A resource that reads from bytes."""

    data: bytes = Field(description="Binary content of the resource")

    async def read(self) -> bytes:
        """Read the binary content."""
        return self.data  # pragma: no cover


class FunctionResource(Resource):
    """A resource that defers data loading by wrapping a function.

    The function is only called when the resource is read, allowing for lazy loading
    of potentially expensive data. This is particularly useful when listing resources,
    as the function won't be called until the resource is actually accessed.

    The function can return:
    - str for text content (default)
    - bytes for binary content
    - other types will be converted to JSON
    """

    fn: Callable[[], Any] = Field(exclude=True)

    async def read(self) -> str | bytes:
        """Read the resource by calling the wrapped function."""
        fn = self.fn
        if is_async_callable(fn):
            result = await fn()
        else:
            result = await anyio.to_thread.run_sync(self.fn)

        if isinstance(result, InputRequiredResult):
            # A static resource function can never read the retry's
            # input_responses (it takes no Context), so this can only be a
            # mistake — reject it instead of JSON-dumping it as content.
            raise ValueError(
                "static resources cannot return InputRequiredResult; only resource "
                "template functions participate in the multi-round-trip flow"
            )
        if isinstance(result, Resource):  # pragma: no cover
            return await result.read()
        elif isinstance(result, bytes):
            return result
        elif isinstance(result, str):
            return result
        else:
            return pydantic_core.to_json(result, fallback=str, indent=2).decode()

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        uri: str,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        icons: list[Icon] | None = None,
        annotations: Annotations | None = None,
        meta: dict[str, Any] | None = None,
    ) -> FunctionResource:
        """Create a FunctionResource from a function."""
        func_name = name or fn.__name__
        if func_name == "<lambda>":  # pragma: no cover
            raise ValueError("You must provide a name for lambda functions")

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            uri=uri,
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            fn=fn,
            icons=icons,
            annotations=annotations,
            meta=meta,
        )


class FileResource(Resource):
    """A resource that reads from a file.

    The file is decoded with `encoding` and served as text, or read as bytes and
    served as a base64 blob when `encoding` is None. When `encoding` is omitted it
    defaults to the `charset` declared in `mime_type`, else `"utf-8-sig"` for
    textual mime types (`text/*`, JSON, XML) and None for everything else; pass
    it explicitly to override either way.
    """

    path: Path = Field(description="Path to the file")
    encoding: str | None = Field(
        default_factory=lambda data: _default_file_encoding(data["mime_type"]),
        description="Text encoding used to decode the file, or None to serve its bytes as a blob",
    )

    @pydantic.field_validator("path")
    @classmethod
    def validate_absolute_path(cls, path: Path) -> Path:
        """Ensure path is absolute."""
        if not path.is_absolute():
            raise ValueError("Path must be absolute")
        return path

    @pydantic.field_validator("encoding")
    @classmethod
    def validate_text_encoding(cls, encoding: str | None) -> str | None:
        """Ensure the encoding names a usable text codec, so a mistake fails at construction not at read."""
        if encoding is not None:
            # Decoding a probe byte rejects both unknown names and codecs that
            # aren't text encodings (base64_codec, rot13, ...) via LookupError.
            try:
                b"x".decode(encoding)
            except LookupError as e:
                raise ValueError(str(e)) from e
            except UnicodeError:
                pass  # a real text encoding; the probe byte just doesn't decode in it
        return encoding

    async def read(self) -> str | bytes:
        """Read the file content."""
        if self.encoding is None:
            return await anyio.to_thread.run_sync(self.path.read_bytes)
        return await anyio.to_thread.run_sync(partial(self.path.read_text, encoding=self.encoding))


class HttpResource(Resource):
    """A resource that reads from an HTTP endpoint."""

    url: str = Field(description="URL to fetch content from")
    mime_type: str = Field(default="application/json", description="MIME type of the resource content")

    async def read(self) -> str | bytes:
        """Read the HTTP content."""
        async with httpx2.AsyncClient() as client:  # pragma: no cover
            response = await client.get(self.url)
            response.raise_for_status()
            return response.text


class DirectoryResource(Resource):
    """A resource that lists files in a directory."""

    path: Path = Field(description="Path to the directory")
    recursive: bool = Field(default=False, description="Whether to list files recursively")
    pattern: str | None = Field(default=None, description="Optional glob pattern to filter files")
    mime_type: str = Field(default="application/json", description="MIME type of the resource content")

    @pydantic.field_validator("path")
    @classmethod
    def validate_absolute_path(cls, path: Path) -> Path:  # pragma: no cover
        """Ensure path is absolute."""
        if not path.is_absolute():
            raise ValueError("Path must be absolute")
        return path

    def list_files(self) -> list[Path]:  # pragma: no cover
        """List files in the directory."""
        if not self.path.exists():
            raise FileNotFoundError(f"Directory not found: {self.path}")
        if not self.path.is_dir():
            raise NotADirectoryError(f"Not a directory: {self.path}")

        if self.pattern:
            return list(self.path.glob(self.pattern)) if not self.recursive else list(self.path.rglob(self.pattern))
        return list(self.path.glob("*")) if not self.recursive else list(self.path.rglob("*"))

    async def read(self) -> str:  # Always returns JSON string  # pragma: no cover
        """Read the directory listing."""
        files = await anyio.to_thread.run_sync(self.list_files)
        file_list = [str(f.relative_to(self.path)) for f in files if f.is_file()]
        return json.dumps({"files": file_list}, indent=2)
