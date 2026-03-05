"""Serializable session state for distributed deployments.

This module provides a SessionState dataclass that can be serialized to JSON
and stored in external storage (Redis, database, etc.) for distributed deployments.

This enables session state to be shared across multiple server instances,
allowing MCP services to run behind load balancers or in horizontally-scaled
deployments.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SessionState(BaseModel):
    """A serializable snapshot of MCP session state.

    This contains the minimal state needed to reconstruct a session context
    across process boundaries. Runtime objects (streams, callbacks) are NOT
    included as they cannot be serialized and must be recreated.

    Attributes:
        session_id: Unique identifier for this session
        protocol_version: MCP protocol version being used
        next_request_id: The next request ID to use (continues sequence)
        server_capabilities: Server capabilities from initialization (as dict)
        server_info: Server metadata from initialization (as dict)
        initialized_sent: Whether the initialized notification was sent
    """

    session_id: str = Field(description="Unique identifier for this session")
    protocol_version: str = Field(description="MCP protocol version being used")
    next_request_id: int = Field(
        description="Next request ID to use",
        ge=0,
    )
    server_capabilities: dict[str, Any] | None = Field(
        default=None,
        description="Server capabilities received during initialization",
    )
    server_info: dict[str, Any] | None = Field(
        default=None,
        description="Server information metadata",
    )
    initialized_sent: bool = Field(
        default=False,
        description="Whether the initialized notification was sent",
    )
