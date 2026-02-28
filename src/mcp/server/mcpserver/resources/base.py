"""Base classes and interfaces for MCPServer resources."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)

from mcp.types import Annotations, Icon

if TYPE_CHECKING:
    from mcp.server.context import LifespanContextT, RequestT
    from mcp.server.mcpserver.server import Context


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
        pattern=r"^[a-zA-Z0-9]+/[a-zA-Z0-9\-+.]+(;\s*[a-zA-Z0-9\-_.]+=[a-zA-Z0-9\-_.]+)*$",
    )
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this resource")
    annotations: Annotations | None = Field(default=None, description="Optional annotations for the resource")
    meta: dict[str, Any] | None = Field(default=None, description="Optional metadata for this resource")

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
    async def read(
        self,
        context: Context[LifespanContextT, RequestT] | None = None,
    ) -> str | bytes:
        """Read the resource content."""
        pass  # pragma: no cover
