"""AI Catalog models (experimental, minimal typed subset).

An AI Catalog is a JSON document advertising AI artifacts, including Server
Cards. The format is owned by the AI Catalog working group
(https://github.com/Agent-Card/ai-catalog). Only the fields the SDK helpers
consume are typed here. Trust and publisher shapes pass through as plain
dictionaries for the host's consent UI.
"""

from typing import Any, Final

from pydantic import model_validator

from mcp.shared.experimental._base import CardModel as _CardModel

__all__ = [
    "AI_CATALOG_MEDIA_TYPE",
    "AI_CATALOG_WELL_KNOWN_PATH",
    "MAX_CATALOG_NESTING_DEPTH",
    "CatalogEntry",
    "AICatalog",
]

AI_CATALOG_MEDIA_TYPE: Final = "application/ai-catalog+json"
"""Media type for AI Catalog documents."""

AI_CATALOG_WELL_KNOWN_PATH: Final = "/.well-known/ai-catalog.json"
"""Well-known path for domain-level catalog discovery."""

MAX_CATALOG_NESTING_DEPTH: Final = 4
"""The AI Catalog spec's cap on nested catalog depth."""


class CatalogEntry(_CardModel):
    """One advertised artifact: a Server Card, a nested catalog, or anything else.

    Exactly one of `url` and `data` must be set. Violations raise
    `pydantic.ValidationError`.
    """

    identifier: str
    type: str
    url: str | None = None
    data: dict[str, Any] | None = None
    display_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    version: str | None = None
    updated_at: str | None = None
    publisher: dict[str, Any] | None = None
    trust_manifest: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one_of_url_or_data(self) -> "CatalogEntry":
        if (self.url is None) == (self.data is None):
            raise ValueError("a catalog entry carries exactly one of url or data")
        return self


class AICatalog(_CardModel):
    """An AI Catalog document (`application/ai-catalog+json`)."""

    spec_version: str
    entries: list[CatalogEntry]
    host: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
