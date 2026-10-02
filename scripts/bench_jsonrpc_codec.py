"""Micro-benchmark: JSONRPCMessage decoding, smart union vs key-presence discriminator.

Compares the previous bare-union adapter (reconstructed in-process) against the
shipped `jsonrpc_message_adapter` over representative payloads, for both decode
paths used by the SDK:

- `validate_json(body)` (client SSE/stdio lines)
- `pydantic_core.from_json(body)` + `validate_python(raw)` (server POST path)

Run with: uv run python scripts/bench_jsonrpc_codec.py [--small N] [--large N]
"""

import argparse
import json
import time
from collections.abc import Callable
from typing import Any

import pydantic_core
from mcp_types.jsonrpc import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)
from pydantic import TypeAdapter

# The adapter as it existed before the discriminator change.
bare_union_adapter: TypeAdapter[Any] = TypeAdapter(
    JSONRPCRequest | JSONRPCNotification | JSONRPCResponse | JSONRPCError
)

SMALL_REQUEST = json.dumps(
    {"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": {"name": "echo", "arguments": {"text": "hi"}}}
).encode()
SMALL_NOTIFICATION = json.dumps(
    {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progressToken": "t", "progress": 0.5}}
).encode()
LARGE_RESULT = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 42,
        "result": {
            "content": [{"type": "text", "text": "x" * 256} for _ in range(64)],
            "structuredContent": {f"key_{i}": {"value": i, "label": "y" * 32} for i in range(64)},
        },
    }
).encode()

REPEATS = 5


def bench_pair(old_fn: Callable[[], Any], new_fn: Callable[[], Any], iterations: int) -> tuple[float, float]:
    """Return best per-call time in microseconds for each adapter over 2*REPEATS rounds.

    Run order alternates each round so warm-up and CPU-state effects are not
    attributed to either adapter.
    """
    fns = (old_fn, new_fn)
    best = [float("inf"), float("inf")]
    for round_index in range(2 * REPEATS):
        order = (0, 1) if round_index % 2 == 0 else (1, 0)
        for key in order:
            start = time.perf_counter()
            for _ in range(iterations):
                fns[key]()
            best[key] = min(best[key], time.perf_counter() - start)
    return best[0] / iterations * 1e6, best[1] / iterations * 1e6


def _decode_validate_json(adapter: TypeAdapter[Any], body: bytes) -> Any:
    return adapter.validate_json(body, by_name=False)


def _decode_two_phase(adapter: TypeAdapter[Any], body: bytes) -> Any:
    return adapter.validate_python(pydantic_core.from_json(body), by_name=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small", type=int, default=100_000, help="iterations for small payloads")
    parser.add_argument("--large", type=int, default=10_000, help="iterations for the large payload")
    args = parser.parse_args()

    payloads = [
        (f"request {len(SMALL_REQUEST)}B", SMALL_REQUEST, args.small),
        (f"notification {len(SMALL_NOTIFICATION)}B", SMALL_NOTIFICATION, args.small),
        (f"result {len(LARGE_RESULT) / 1024:.1f}KB", LARGE_RESULT, args.large),
    ]
    decoders: list[tuple[str, Callable[[TypeAdapter[Any], bytes], Any]]] = [
        ("validate_json", _decode_validate_json),
        ("two-phase", _decode_two_phase),
    ]
    print(f"{'payload':<20} {'path':<14} {'smart union':>12} {'discriminator':>14} {'speedup':>8}")
    for label, body, iterations in payloads:
        for path_label, decode in decoders:
            old, new = bench_pair(
                lambda: decode(bare_union_adapter, body),
                lambda: decode(jsonrpc_message_adapter, body),
                iterations,
            )
            print(f"{label:<20} {path_label:<14} {old:>10.2f}us {new:>12.2f}us {old / new:>7.2f}x")


if __name__ == "__main__":
    main()
