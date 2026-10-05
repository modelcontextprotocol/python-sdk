"""AI Catalogs — shared types.

WARNING: These APIs are experimental and may change without notice.

An AI Catalog is a JSON index of AI artifacts (MCP Server Cards among them)
published at ``/.well-known/ai-catalog.json`` for domain-level discovery. See
``mcp.shared.experimental.ai_catalog.types`` for the model definitions.

* Servers generate and serve a catalog with ``mcp.server.experimental.ai_catalog``.
* Clients ingest one with ``mcp.client.experimental.ai_catalog``.
"""

from mcp.shared.experimental.ai_catalog.types import (
    AI_CATALOG_MEDIA_TYPE,
    AI_CATALOG_URN_PREFIX,
    AI_CATALOG_WELL_KNOWN_PATH,
    MCP_SERVER_CARD_MEDIA_TYPE,
    AICatalog,
    Attestation,
    CatalogEntry,
    HostInfo,
    ProvenanceLink,
    Publisher,
    TrustManifest,
    TrustSchema,
)

__all__ = [
    "AI_CATALOG_MEDIA_TYPE",
    "AI_CATALOG_URN_PREFIX",
    "AI_CATALOG_WELL_KNOWN_PATH",
    "MCP_SERVER_CARD_MEDIA_TYPE",
    "AICatalog",
    "Attestation",
    "CatalogEntry",
    "HostInfo",
    "ProvenanceLink",
    "Publisher",
    "TrustManifest",
    "TrustSchema",
]
