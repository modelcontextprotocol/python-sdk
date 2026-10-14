"""Outbound JSON-RPC wire serialization shared by transports.

`model_dump_json` is the normal path. Lone surrogates (and any other value that
survives `model_dump(mode="json")` but fails the final UTF-8 encode) must not
tear down a writer task: one bad message costs only itself.
"""

from __future__ import annotations

import logging

from mcp_types import INTERNAL_ERROR, ErrorData, JSONRPCError, JSONRPCMessage, JSONRPCResponse

logger = logging.getLogger(__name__)


def serialize_jsonrpc_message(message: JSONRPCMessage) -> str:
    """Serialize a JSON-RPC message the way transports always have."""
    return message.model_dump_json(by_alias=True, exclude_unset=True)


def serialize_outbound_message(message: JSONRPCMessage) -> str | None:
    """Serialize for the wire; never raise for a single unserializable message.

    On failure:
    - A response or error with an id becomes ``Internal server error`` (same
      shape as other handler serialization failures higher in the stack).
    - A request, notification, or id-less error returns ``None`` so the caller
      can drop it or fail that request locally without closing the session.
    """
    try:
        return serialize_jsonrpc_message(message)
    except Exception:
        logger.exception("Failed to serialize outbound JSON-RPC message")
        return _fallback_after_serialization_failure(message)


def _fallback_after_serialization_failure(message: JSONRPCMessage) -> str | None:
    if isinstance(message, JSONRPCResponse | JSONRPCError) and message.id is not None:
        replacement = JSONRPCError(
            jsonrpc="2.0",
            id=message.id,
            error=ErrorData(code=INTERNAL_ERROR, message="Internal server error"),
        )
        try:
            return serialize_jsonrpc_message(replacement)
        except Exception:  # pragma: no cover
            logger.exception("Failed to serialize serialization-error fallback")
            return None
    return None
