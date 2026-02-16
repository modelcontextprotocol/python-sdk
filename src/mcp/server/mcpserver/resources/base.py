"""Base classes and interfaces for MCPServer resources."""

import abc
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from mcp.types import Annotations, Icon


class Resource(BaseModel, abc.ABC):
    """Base class for all resources."""

    model_config = ConfigDict(validate_default=True)

    uri: str = Field(default=..., description="URI of the resource")
    name: str | None = Field(description="Name of the resource", default=None)
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of the resource", default=None)
    mime_type: str = Field(
        default="text/plain",
        description="MIME type of the resource content",
    )
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this resource")
    annotations: Annotations | None = Field(default=None, description="Optional annotations for the resource")
    meta: dict[str, Any] | None = Field(default=None, description="Optional metadata for this resource")

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        """Validate that mime_type has a basic type/subtype structure.

        The MCP spec defines mimeType as an optional string with no format
        constraints. This validator only checks for the minimal type/subtype
        structure to catch obvious mistakes, without restricting valid MIME
        types per RFC 2045.
        """
        if "/" not in value:
            raise ValueError(
                f"Invalid MIME type '{value}': must contain a '/' separating type and subtype "
                f"(e.g. 'text/plain', 'application/json')"
            )
        return value

    @field_validator("name", mode="before")
    @classmethod
    def set_default_name(cls, name: str | None, info: ValidationInfo) -> str:
        """Set default name from URI if not provided."""
        if name:
            return name
        if uri := info.data.get("uri"):
            return str(uri)
        raise ValueError("Either name or uri must be provided")

    @abc.abstractmethod
    async def read(self) -> str | bytes:
        """Read the resource content."""
        pass  # pragma: no cover
