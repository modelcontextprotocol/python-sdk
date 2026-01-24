"""MCP V2 Session - Protocol-level session state from the init handshake."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from mcp_v2.types.common import ClientCapabilities, Implementation


@dataclass(frozen=True)
class SessionInfo:
    """Immutable protocol-level session state, created during the init handshake.

    This is pure data — not a god-object with methods, receive loops, or state machines.
    Transport-level session state (event stores, pending responses) lives elsewhere.
    """

    client_info: Implementation
    client_capabilities: ClientCapabilities
    protocol_version: str
    session_id: str = field(default_factory=lambda: uuid4().hex)
