"""Ingest AI Catalogs.

WARNING: These APIs are experimental and may change without notice.

A client discovers the AI artifacts a host advertises by fetching its catalog
from the well-known location::

    from mcp.client.experimental.ai_catalog import fetch_ai_catalog, well_known_ai_catalog_url

    catalog = await fetch_ai_catalog(well_known_ai_catalog_url("https://dice.example.com"))
    for entry in catalog.entries:
        print(entry.identifier, entry.media_type, entry.url)

For the MCP-specific flow — fetch the catalog and the Server Cards it
advertises in one call — see
``mcp.client.experimental.server_card.discover_server_cards``.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx

from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.experimental.ai_catalog.types import (
    AI_CATALOG_MEDIA_TYPE,
    AI_CATALOG_WELL_KNOWN_PATH,
    AICatalog,
)

__all__ = ["well_known_ai_catalog_url", "fetch_ai_catalog"]


def well_known_ai_catalog_url(url: str, *, well_known_path: str = AI_CATALOG_WELL_KNOWN_PATH) -> str:
    """Resolve the well-known AI Catalog URL for a server's origin.

    Accepts either a bare origin (``https://example.com``) or any URL on the
    server (e.g. its ``/mcp`` endpoint); the catalog lives at the host root.

    Raises:
        ValueError: If ``url`` is not an absolute http(s) URL.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"Expected an absolute http(s) URL, got {url!r}")
    return urljoin(f"{parts.scheme}://{parts.netloc}", well_known_path)


async def fetch_ai_catalog(url: str, *, http_client: httpx.AsyncClient | None = None) -> AICatalog:
    """Fetch and validate the AI Catalog at ``url``.

    ``url`` is fetched as-is — catalogs are location-independent; use
    :func:`well_known_ai_catalog_url` to resolve a host's conventional
    location. Pass an existing ``http_client`` to reuse connection pooling /
    auth, otherwise a short-lived client with MCP defaults is used.

    Raises:
        httpx.HTTPError: If the request fails or returns a non-2xx status.
        pydantic.ValidationError: If the document is not a valid AI Catalog.
    """
    if http_client is None:
        async with create_mcp_http_client() as client:
            return await fetch_ai_catalog(url, http_client=client)
    response = await http_client.get(url, headers={"Accept": f"{AI_CATALOG_MEDIA_TYPE}, application/json"})
    response.raise_for_status()
    return AICatalog.model_validate(response.json())
