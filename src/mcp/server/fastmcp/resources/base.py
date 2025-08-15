"""Base classes and interfaces for FastMCP resources."""

import abc
from typing import Annotated

from pydantic import (
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    UrlConstraints,
    ValidationInfo,
    field_validator,
)


class Resource(BaseModel, abc.ABC):
    """Base class for all MCP resources.

    Resources provide contextual data that can be read by LLMs. Each resource
    has a URI, optional metadata like name and description, and content that
    can be retrieved via the read() method.

    Attributes:
        uri: Unique identifier for the resource
        name: Optional name for the resource (defaults to URI if not provided)
        title: Optional human-readable title
        description: Optional description of the resource content
        mime_type: MIME type of the resource content (defaults to text/plain)
    """

    model_config = ConfigDict(validate_default=True)

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)] = Field(default=..., description="URI of the resource")
    name: str | None = Field(description="Name of the resource", default=None)
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of the resource", default=None)
    mime_type: str = Field(
        default="text/plain",
        description="MIME type of the resource content",
        pattern=r"^[a-zA-Z0-9]+/[a-zA-Z0-9\-+.]+$",
    )

    @field_validator("name", mode="before")
    @classmethod
    def set_default_name(cls, name: str | None, info: ValidationInfo) -> str:
        """Set default name from URI if not provided.

        Args:
            name: The provided name value
            info: Pydantic validation info containing other field values

        Returns:
            The name to use for the resource

        Raises:
            ValueError: If neither name nor uri is provided
        """
        if name:
            return name
        if uri := info.data.get("uri"):
            return str(uri)
        raise ValueError("Either name or uri must be provided")

    @abc.abstractmethod
    async def read(self) -> str | bytes:
        """Read the resource content.

        Returns:
            The resource content as either a string or bytes

        Raises:
            ResourceError: If the resource cannot be read
        """
        pass
