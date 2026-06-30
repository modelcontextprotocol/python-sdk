"""Guard against 2026-era protocol vocabulary leaking onto legacy (2025-era) exchanges.

The 2026-07-28 spec revision introduces wire vocabulary that did not exist before it --
result-envelope fields (`resultType`, `ttlMs`, `cacheScope`), namespaced
`io.modelcontextprotocol/*` `_meta` keys, the version literal itself, and the per-request HTTP
headers `Mcp-Method` / `Mcp-Name` / `Mcp-Param-*`. None of that may appear on a connection
negotiated at an earlier protocol version: a test that records a plain legacy round trip and
runs it through :func:`assert_no_modern_vocabulary` will start failing the moment a 2026 change
leaks onto the existing wire.

Tests construct a :class:`RecordedExchange` from whatever instrumentation they have to hand --
the `on_request` / `on_response` hooks on :func:`tests.interaction._connect.mounted_app` for the
HTTP seam, and :class:`tests.interaction._helpers.RecordingTransport` for the JSON-RPC frames --
and pass it to the assertion. The helper scans header names and serialised bodies; it makes no
assumptions about which side produced what.
"""

from dataclasses import dataclass

import httpx2
from mcp_types import JSONRPCMessage, jsonrpc_message_adapter

#: Substrings that must not appear anywhere in a request body or JSON-RPC frame on a legacy
#: exchange. Matching is by raw substring against the by-alias JSON serialisation, so a leaked
#: field name, `_meta` key prefix, or version literal is caught regardless of where in the
#: payload it sits.
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
    """Everything a test captured from one streamable-HTTP conversation, for vocabulary scanning.

    `requests` and `responses` are inspected for header names and (for requests) body bytes;
    `frames` are re-serialised to their wire JSON and scanned as body text. Response bodies are
    not read here -- streamable-HTTP responses are SSE streams that are consumed elsewhere -- so
    the server-to-client body content must be supplied via `frames`.
    """

    requests: list[httpx2.Request]
    responses: list[httpx2.Response]
    frames: list[JSONRPCMessage]


def assert_no_modern_vocabulary(recorded: RecordedExchange) -> None:
    """Fail if any 2026-era header name or body token appears anywhere in `recorded`.

    All findings are collected before asserting so a single failure reports every leak.
    """
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
