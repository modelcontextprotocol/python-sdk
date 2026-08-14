"""Base classes and interfaces for MCPServer resources."""

import abc
from typing import Any

from mcp_types import Annotations, Icon
from mcp_types._deferred import deferred_model as _deferred_model
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
)


@_deferred_model
class Resource(BaseModel, abc.ABC):
    """Base class for all resources."""

    # defer_build: build the validator on first use rather than at import (import-time cost);
    # inherited by every Resource subclass.
    model_config = ConfigDict(validate_default=True, extra="forbid", defer_build=True)

    uri: str = Field(default=..., description="URI of the resource")
    name: str | None = Field(description="Name of the resource", default=None)
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of the resource", default=None)
    mime_type: str = Field(default="text/plain", description="MIME type of the resource content")
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
    async def read(self) -> str | bytes:
        """Read the resource content."""
        pass  # pragma: no cover
