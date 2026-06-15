"""Shared pydantic bases for the `mcp.types.v*` wire-shape packages.

No alias generator is configured: every wire name is an explicit
`Field(alias=...)` so each surface file shows exactly what goes on the wire.
"""

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    """Base for surface-package models: unknown fields are accepted and dropped."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class OpenWireModel(BaseModel):
    """Base for `_meta` carrier models: unknown fields are retained for round-tripping."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")
