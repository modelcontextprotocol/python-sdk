"""Concrete resource implementations."""

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import httpx
import pydantic
import pydantic_core
from pydantic import AnyUrl, Field, ValidationInfo, validate_call

from mcp.server.fastmcp.resources.base import Resource
from mcp.server.fastmcp.utilities.context_injection import find_context_parameter
from mcp.types import Annotations, Icon


class TextResource(Resource):
    """A resource that reads from a string."""

    text: str = Field(description="Text content of the resource")

    async def read(self, context: Any | None = None) -> str:
        """Read the text content."""
        return self.text


class BinaryResource(Resource):
    """A resource that reads from bytes."""

    data: bytes = Field(description="Binary content of the resource")

    async def read(self, context: Any | None = None) -> bytes:
        """Read the binary content."""
        return self.data


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
    context_kwarg: str | None = Field(None, exclude=True)

    async def read(self, context: Any | None = None) -> str | bytes:
        """Read the resource content by calling the function."""
        args = {}
        if self.context_kwarg:
            args[self.context_kwarg] = context

        try:
            if inspect.iscoroutinefunction(self.fn):
                result = await self.fn(**args)
            else:
                result = self.fn(**args)

            if isinstance(result, str | bytes):
                return result
            if isinstance(result, pydantic.BaseModel):
                return result.model_dump_json(indent=2)

            # For other types, convert to a JSON string
            try:
                return json.dumps(pydantic_core.to_jsonable_python(result))
            except pydantic_core.PydanticSerializationError:
                return json.dumps(str(result))
        except Exception as e:
            raise ValueError(f"Error reading resource {self.uri}: {e}")

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
    ) -> "FunctionResource":
        """Create a FunctionResource from a function."""
        func_name = name or fn.__name__
        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        context_kwarg = find_context_parameter(fn)

        # ensure the arguments are properly cast
        fn = validate_call(fn)

        return cls(
            uri=AnyUrl(uri),
            name=func_name,
            title=title,
            description=description or fn.__doc__ or "",
            mime_type=mime_type or "text/plain",
            fn=fn,
            icons=icons,
            context_kwarg=context_kwarg,
            annotations=annotations,
        )


class FileResource(Resource):
    """A resource that reads from a file.

    Set is_binary=True to read file as binary data instead of text.
    """

    path: Path = Field(description="Path to the file")
    is_binary: bool = Field(
        default=False,
        description="Whether to read the file as binary data",
    )
    mime_type: str = Field(
        default="text/plain",
        description="MIME type of the resource content",
    )

    @pydantic.field_validator("path")
    @classmethod
    def validate_absolute_path(cls, path: Path) -> Path:
        """Ensure path is absolute."""
        if not path.is_absolute():
            raise ValueError("Path must be absolute")
        return path

    @pydantic.field_validator("is_binary")
    @classmethod
    def set_binary_from_mime_type(cls, is_binary: bool, info: ValidationInfo) -> bool:
        """Set is_binary based on mime_type if not explicitly set."""
        if is_binary:
            return True
        mime_type = info.data.get("mime_type", "text/plain")
        return not mime_type.startswith("text/")

    async def read(self, context: Any | None = None) -> str | bytes:
        """Read the file content."""
        try:
            if self.is_binary:
                return await anyio.to_thread.run_sync(self.path.read_bytes)
            return await anyio.to_thread.run_sync(self.path.read_text)
        except Exception as e:
            raise ValueError(f"Error reading file {self.path}: {e}")


class HttpResource(Resource):
    """A resource that reads from an HTTP endpoint."""

    url: str = Field(description="URL to fetch content from")
    mime_type: str = Field(default="application/json", description="MIME type of the resource content")

    async def read(self, context: Any | None = None) -> str | bytes:
        """Read the HTTP content."""
        async with httpx.AsyncClient() as client:
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
    def validate_absolute_path(cls, path: Path) -> Path:
        """Ensure path is absolute."""
        if not path.is_absolute():
            raise ValueError("Path must be absolute")
        return path

    def list_files(self) -> list[Path]:
        """List files in the directory."""
        if not self.path.exists():
            raise FileNotFoundError(f"Directory not found: {self.path}")
        if not self.path.is_dir():
            raise NotADirectoryError(f"Not a directory: {self.path}")

        try:
            if self.pattern:
                return list(self.path.glob(self.pattern)) if not self.recursive else list(self.path.rglob(self.pattern))
            return list(self.path.glob("*")) if not self.recursive else list(self.path.rglob("*"))
        except Exception as e:
            raise ValueError(f"Error listing directory {self.path}: {e}")

    async def read(self, context: Any | None = None) -> str:  # Always returns JSON string
        """Read the directory listing."""
        try:
            files = await anyio.to_thread.run_sync(self.list_files)
            file_list = [str(f.relative_to(self.path)) for f in files if f.is_file()]
            return json.dumps({"files": file_list}, indent=2)
        except Exception as e:
            raise ValueError(f"Error reading directory {self.path}: {e}")
