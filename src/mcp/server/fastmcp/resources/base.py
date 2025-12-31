"""Base classes and interfaces for FastMCP resources."""

import abc
import re
from email.message import Message
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

from mcp.types import Annotations, Icon


class Resource(BaseModel, abc.ABC):
    """Base class for all resources."""

    model_config = ConfigDict(validate_default=True)

    uri: Annotated[AnyUrl, UrlConstraints(host_required=False)] = Field(default=..., description="URI of the resource")
    name: str | None = Field(description="Name of the resource", default=None)
    title: str | None = Field(description="Human-readable title of the resource", default=None)
    description: str | None = Field(description="Description of the resource", default=None)
    mime_type: str = Field(
        default="text/plain",
        description="MIME type of the resource content",
    )
    icons: list[Icon] | None = Field(default=None, description="Optional list of icons for this resource")
    annotations: Annotations | None = Field(default=None, description="Optional annotations for the resource")

    @field_validator("name", mode="before")
    @classmethod
    def set_default_name(cls, name: str | None, info: ValidationInfo) -> str:
        """Set default name from URI if not provided."""
        if name:
            return name
        if uri := info.data.get("uri"):
            return str(uri)
        raise ValueError("Either name or uri must be provided")

    @field_validator("mime_type")
    @classmethod
    def validate_mimetype(cls, mime_type: str) -> str:
        """Validate MIME type. The default mime type is 'text/plain'"""
        print(f"The mime type received is: {mime_type}")
        _mime_type = mime_type.strip()
        if not _mime_type or "/" not in _mime_type:
            raise ValueError(
                f"Invalid MIME type: '{mime_type}'. Must follow 'type/subtype' format. "
                "It looks like you provided a parameter without a type."
            )

        m = Message()  # RFC 2045 compliant parser
        m["Content-Type"] = _mime_type
        main_type, sub_type, params = m.get_content_maintype(), m.get_content_subtype(), m.get_params()
        print(f"Main type and subtype and params are: {main_type} and {sub_type} and {params}")

        # RFC 2045 tokens allow alphanumeric plus !#$%&'*+-.^_`|~
        token_pattern = r"^[a-zA-Z0-9!#$%&'*+\-.^_`|~]+$"
        if (
            not main_type
            or not re.match(token_pattern, main_type)
            or not sub_type
            or not re.match(token_pattern, sub_type)
            # The first element of params is usually the type/subtype itself.
            or not params
            or params[0] != (f"{main_type}/{sub_type}", "")
        ):
            raise ValueError(f"Invalid MIME type: {mime_type}. The main type or sub type is invalid.")

        # No format validation on parameter key/value.
        if params and len(params) > 1:
            for key, val in params[1:]:
                # An attribute MUST have a name. The value CAN be empty.
                if not key.strip():
                    raise ValueError(f"Malformed parameter in '{val}': missing attribute name.")

        return mime_type

    @abc.abstractmethod
    async def read(self) -> str | bytes:
        """Read the resource content."""
        pass  # pragma: no cover
