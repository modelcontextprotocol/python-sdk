"""Base class for the generated spec-oracle models in this directory."""

from pydantic import BaseModel, ConfigDict


class OracleModel(BaseModel):
    """Base for generated spec-oracle models.

    No alias generator on purpose: every wire alias must be explicit in the
    generated code so the oracle cannot inherit (or mask) SDK serialization
    behavior.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")
