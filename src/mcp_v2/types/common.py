"""MCP Common Types - Shared types used across the protocol."""

from typing import Annotated, Any, Literal

from pydantic import Field

from mcp_v2.types.base import MCPModel


class Icon(MCPModel):
    """An optionally-sized icon that can be displayed in a user interface."""

    src: str
    mime_type: Annotated[str | None, Field(alias="mimeType")] = None
    sizes: list[str] | None = None
    theme: Literal["light", "dark"] | None = None


class Annotations(MCPModel):
    """Optional annotations for the client."""

    audience: list[Literal["user", "assistant"]] | None = None
    priority: Annotated[float | None, Field(ge=0.0, le=1.0)] = None
    last_modified: Annotated[str | None, Field(alias="lastModified")] = None


class Implementation(MCPModel):
    """Describes the name and version of an MCP implementation."""

    name: str
    version: str
    title: str | None = None
    description: str | None = None
    icons: list[Icon] | None = None
    website_url: Annotated[str | None, Field(alias="websiteUrl")] = None


class ClientCapabilities(MCPModel):
    """Capabilities that a client may support."""

    experimental: dict[str, Any] | None = None
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None
    tasks: dict[str, Any] | None = None


class ServerCapabilities(MCPModel):
    """Capabilities that a server may support."""

    experimental: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    completions: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    tools: dict[str, Any] | None = None
    tasks: dict[str, Any] | None = None
