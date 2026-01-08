"""
This module provides simpler types to use with the server for managing prompts
and tools.
"""

from pydantic import BaseModel

from mcp.types import (
    Icon,
    ServerCapabilities,
)


class InitializationOptions(BaseModel):
    server_name: str
    server_version: str
    title: str | None = None
    description: str | None = None
    capabilities: ServerCapabilities
    instructions: str | None = None
    website_url: str | None = None
    icons: list[Icon] | None = None
