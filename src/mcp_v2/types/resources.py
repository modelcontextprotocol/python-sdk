"""MCP Resource Types - Types for resources."""

from typing import Annotated

from pydantic import Field
from pydantic.networks import AnyUrl, UrlConstraints

from mcp_v2.types.base import MCPModel, Meta
from mcp_v2.types.common import Annotations, Icon

# URI type that allows any protocol (no host required)
Uri = Annotated[AnyUrl, UrlConstraints(host_required=False)]


class ResourceContents(MCPModel):
    """The contents of a specific resource or sub-resource."""

    uri: Uri
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class TextResourceContents(ResourceContents):
    """Text contents of a resource."""

    text: str


class BlobResourceContents(ResourceContents):
    """Binary contents of a resource (base64 encoded)."""

    blob: str


class Resource(MCPModel):
    """A known resource that the server is capable of reading."""

    uri: Uri
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    annotations: Annotations | None = None
    size: int | None = None
    icons: list[Icon] | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class ResourceTemplate(MCPModel):
    """A template description for resources available on the server."""

    uri_template: Annotated[str, Field(alias="uriTemplate")]
    name: str
    title: str | None = None
    description: str | None = None
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    annotations: Annotations | None = None
    icons: list[Icon] | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None
