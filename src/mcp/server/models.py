"""Simplified types for use with the server."""

from mcp_types import Icon, ServerCapabilities
from pydantic import BaseModel


class InitializationOptions(BaseModel):
    server_name: str
    server_version: str
    title: str | None = None
    description: str | None = None
    capabilities: ServerCapabilities
    instructions: str | None = None
    website_url: str | None = None
    icons: list[Icon] | None = None
