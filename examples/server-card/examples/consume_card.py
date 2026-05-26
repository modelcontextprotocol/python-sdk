"""Client side: fetch and validate a Server Card, then act on it.

    python examples/consume_card.py http://127.0.0.1:8000

Given a server URL (origin or any URL on the host), this resolves the
``.well-known`` location, fetches the card, validates it against the JSON Schema
+ semantic rules, and prints what a client would use to connect.
"""

from __future__ import annotations

import asyncio
import sys

from mcp_server_card import ServerCardValidationError, fetch_server_card, well_known_url


async def main(server_url: str) -> int:
    print(f"Resolving card: {well_known_url(server_url)}")
    try:
        card = await fetch_server_card(server_url)
    except ServerCardValidationError as exc:
        print("Card failed validation:")
        for error in exc.errors:
            print(f"  - {error}")
        return 1

    print(f"\n{card.title or card.name} ({card.name} v{card.version})")
    print(f"  {card.description}")
    if card.repository:
        print(f"  source: {card.repository.url}")
    for remote in card.remotes or []:
        versions = ", ".join(remote.supported_protocol_versions or []) or "unspecified"
        print(f"  remote [{remote.type}]: {remote.url}  (protocols: {versions})")
        for header in remote.headers or []:
            flags = "required" if header.is_required else "optional"
            secret = ", secret" if header.is_secret else ""
            print(f"      header {header.name} ({flags}{secret})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
