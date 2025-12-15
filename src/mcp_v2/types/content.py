"""MCP Content Types - Content block types used in prompts and tool results."""

from typing import Annotated, Literal

from pydantic import Field

from mcp_v2.types.base import MCPModel, Meta
from mcp_v2.types.common import Annotations
from mcp_v2.types.resources import (
    BlobResourceContents,
    Resource,
    TextResourceContents,
)


class TextContent(MCPModel):
    """Text provided to or from an LLM."""

    type: Literal["text"] = "text"
    text: str
    annotations: Annotations | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class ImageContent(MCPModel):
    """An image provided to or from an LLM."""

    type: Literal["image"] = "image"
    data: str  # base64 encoded
    mime_type: Annotated[str, Field(alias="mimeType")]
    annotations: Annotations | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class AudioContent(MCPModel):
    """Audio provided to or from an LLM."""

    type: Literal["audio"] = "audio"
    data: str  # base64 encoded
    mime_type: Annotated[str, Field(alias="mimeType")]
    annotations: Annotations | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


class ResourceLink(Resource):
    """A resource link that can be included in content."""

    type: Literal["resource_link"] = "resource_link"


class EmbeddedResource(MCPModel):
    """The contents of a resource, embedded into a prompt or tool call result."""

    type: Literal["resource"] = "resource"
    resource: TextResourceContents | BlobResourceContents
    annotations: Annotations | None = None
    meta: Annotated[Meta | None, Field(alias="_meta")] = None


# Content block union - all possible content types in prompts and tool results
ContentBlock = TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource
