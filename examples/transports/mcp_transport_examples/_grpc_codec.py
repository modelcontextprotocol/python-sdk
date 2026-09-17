"""JSON payloads inside the experimental protobuf binding."""

from __future__ import annotations

import json
from typing import Any, NoReturn, cast

MAX_PAYLOAD_SIZE = 4 * 1024 * 1024
RPC_METHOD = "/mcp.transport.example.MCP/Call"


def encode_json(value: Any) -> bytes:
    payload = json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError("Payload exceeds the gRPC binding's size limit")
    return payload


def decode_json(payload: bytes) -> Any:
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError("Payload exceeds the gRPC binding's size limit")
    return json.loads(payload, parse_constant=reject_constant)


def decode_object(payload: bytes, *, nullable: bool = False) -> dict[str, Any] | None:
    value = decode_json(payload)
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    if nullable and value is None:
        return None
    raise ValueError("Expected a JSON object")


def reject_constant(value: str) -> NoReturn:
    raise ValueError(f"Invalid JSON constant: {value}")
