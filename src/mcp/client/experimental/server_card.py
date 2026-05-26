"""Ingest MCP Server Cards (SEP-2127).

WARNING: These APIs are experimental and may change without notice.

A client discovers how to connect to a remote server by fetching its card from
the conventional ``.well-known`` location before initializing a session::

    from mcp.client.experimental.server_card import fetch_server_card

    card = await fetch_server_card("https://dice.example.com")
    for remote in card.remotes or []:
        print(remote.type, remote.url, remote.supported_protocol_versions)

The returned :class:`ServerCard` is fully validated; malformed documents raise
``pydantic.ValidationError``.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from mcp.shared.experimental.server_card.types import WELL_KNOWN_PATH, ServerCard

__all__ = ["well_known_url", "fetch_server_card", "load_server_card"]


def well_known_url(url: str, *, well_known_path: str = WELL_KNOWN_PATH) -> str:
    """Resolve the Server Card URL for a server's origin.

    Accepts either a bare origin (``https://example.com``) or any URL on the
    server (e.g. its ``/mcp`` endpoint); the card always lives at the host root.

    Raises:
        ValueError: If ``url`` is not an absolute http(s) URL.
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
    httpx_client: httpx.AsyncClient | None = None,
) -> ServerCard:
    """Fetch and validate the Server Card for the server at ``url``.

    ``url`` may be the server's origin or any URL on the same host; the card is
    resolved to ``<origin><well_known_path>``. Pass an existing ``httpx_client``
    to reuse connection pooling / auth, otherwise a short-lived client is used.

    Raises:
        ValueError: If ``url`` is not an absolute http(s) URL.
        httpx.HTTPError: If the request fails or returns a non-2xx status.
        pydantic.ValidationError: If the document is not a valid Server Card.
    """
    target = well_known_url(url, well_known_path=well_known_path)

    if httpx_client is None:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(target, headers={"Accept": "application/json"})
    else:
        response = await httpx_client.get(target, headers={"Accept": "application/json"})
    response.raise_for_status()
    return ServerCard.model_validate(response.json())


def load_server_card(path: str | Path) -> ServerCard:
    """Load and validate a Server Card from a JSON file.

    Raises:
        OSError: If the file cannot be read.
        json.JSONDecodeError: If the file is not valid JSON.
        pydantic.ValidationError: If the document is not a valid Server Card.
    """
    text = Path(path).read_text(encoding="utf-8")
    return ServerCard.model_validate(json.loads(text))
