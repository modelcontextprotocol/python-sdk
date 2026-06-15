"""Shared pydantic base for the generated ``mcp.types.v*`` wire-shape packages."""

from pydantic import BaseModel, ConfigDict


class WireModel(BaseModel):
    """Base for generated wire models: enables ``populate_by_name``; subclasses set ``extra="allow"`` themselves."""

    model_config = ConfigDict(populate_by_name=True)
