"""This module provides simplified types to use with the server for managing prompts
and tools.
"""

from mcp_types import Icon, ServerCapabilities
from mcp_types._deferred import deferred_model as _deferred_model
from pydantic import BaseModel, ConfigDict


@_deferred_model
class InitializationOptions(BaseModel):
    # defer_build: build the validator on first use rather than at import (import-time cost).
    model_config = ConfigDict(defer_build=True)

    server_name: str
    server_version: str
    title: str | None = None
    description: str | None = None
    capabilities: ServerCapabilities
    instructions: str | None = None
    website_url: str | None = None
    icons: list[Icon] | None = None
