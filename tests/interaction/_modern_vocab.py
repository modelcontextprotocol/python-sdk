"""Guard against 2026-07-28 protocol vocabulary leaking onto exchanges negotiated at an earlier version.

Tests record a legacy round trip into a `RecordedExchange` -- via the `on_request` / `on_response`
hooks on `tests.interaction._connect.mounted_app` and `tests.interaction._helpers.RecordingTransport`
-- and pass it to `assert_no_modern_vocabulary`, which scans header names and serialised bodies
without assuming which side produced what.
"""

from dataclasses import dataclass

import httpx
from mcp_types import JSONRPCMessage, jsonrpc_message_adapter

#: Substrings forbidden in request bodies and JSON-RPC frames on a legacy exchange; matched raw
#: against the by-alias JSON serialisation, so a leak is caught wherever it sits in the payload.
MODERN_BODY_TOKENS: frozenset[str] = frozenset(
    {
        "resultType",
        "ttlMs",
        "cacheScope",
        "io.modelcontextprotocol/",
        "2026-07-28",
    }
)

#: Lower-cased HTTP header names introduced by the 2026-07-28 transport.
MODERN_HEADER_NAMES: frozenset[str] = frozenset({"mcp-method", "mcp-name"})

#: Lower-cased prefix for the 2026-07-28 per-parameter header family.
MODERN_HEADER_PREFIX = "mcp-param-"


@dataclass
class RecordedExchange:
    """One captured streamable-HTTP conversation, for vocabulary scanning.

    Response bodies are not read here -- they are SSE streams consumed elsewhere -- so
    server-to-client content must be supplied via `frames`.
    """

    requests: list[httpx.Request]
    responses: list[httpx.Response]
    frames: list[JSONRPCMessage]


def assert_no_modern_vocabulary(recorded: RecordedExchange) -> None:
    """Fail if any 2026-era header name or body token appears in `recorded`, reporting all leaks at once."""
    header_names = [name.lower() for request in recorded.requests for name in request.headers]
    header_names += [name.lower() for response in recorded.responses for name in response.headers]
    leaked = [
        f"header {name!r}"
        for name in header_names
        if name in MODERN_HEADER_NAMES or name.startswith(MODERN_HEADER_PREFIX)
    ]

    corpus = b"".join(request.content for request in recorded.requests).decode()
    corpus += "".join(
        jsonrpc_message_adapter.dump_json(frame, by_alias=True, exclude_none=True).decode() for frame in recorded.frames
    )
    leaked.extend(f"body token {token!r}" for token in MODERN_BODY_TOKENS if token in corpus)

    assert not leaked, f"Modern (2026-07-28) protocol vocabulary on a legacy exchange: {leaked}"
