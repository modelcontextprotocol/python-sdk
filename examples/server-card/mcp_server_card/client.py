"""Client-side consumption of MCP Server Cards.

A client typically knows a server's base URL and wants to discover how to
connect *before* initializing a session. These helpers fetch the card from the
conventional ``.well-known`` location (or load it from disk/string), validate
it, and hand back typed models.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from .types import ServerCard
from .validation import parse_server_card

__all__ = [
    "WELL_KNOWN_PATH",
    "well_known_url",
    "fetch_server_card",
    "load_server_card",
]

#: Conventional path a Server Card is published at, relative to the host root.
WELL_KNOWN_PATH = "/.well-known/mcp/server-card"


def well_known_url(url: str, *, well_known_path: str = WELL_KNOWN_PATH) -> str:
    """Resolve the Server Card URL for a server's origin.

    Accepts either a bare origin (``https://example.com``) or any URL on the
    server (e.g. its ``/mcp`` endpoint); the card always lives at the host root.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"Expected an absolute http(s) URL, got {url!r}")
    origin = f"{parts.scheme}://{parts.netloc}"
    return urljoin(origin, well_known_path)


async def fetch_server_card(
    url: str,
    *,
    well_known_path: str = WELL_KNOWN_PATH,
    client: httpx.AsyncClient | None = None,
    validate: bool = True,
) -> ServerCard:
    """Fetch and validate a Server Card for the server at ``url``.

    ``url`` may be the server's origin or any URL on the same host. Pass an
    existing ``httpx.AsyncClient`` to reuse connection pooling / auth; otherwise
    a short-lived client is created. Set ``validate=False`` to skip JSON Schema
    validation (still parses into the typed model).
    """
    target = well_known_url(url, well_known_path=well_known_path)

    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        response = await client.get(target, headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
    finally:
        if owns_client:
            await client.aclose()

    if validate:
        return parse_server_card(data)
    return ServerCard.model_validate(data)


def load_server_card(source: str | Path, *, validate: bool = True) -> ServerCard:
    """Load a Server Card from a file path or a JSON string."""
    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith("{")):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = source
    data = json.loads(text)
    if validate:
        return parse_server_card(data)
    return ServerCard.model_validate(data)
