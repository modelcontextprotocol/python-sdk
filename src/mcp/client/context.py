"""Request context for MCP client handlers."""

from mcp.client import BaseClientSession
from mcp.shared._context import RequestContext

ClientRequestContext = RequestContext[BaseClientSession]
"""Context for handling incoming requests in a client session.

This context is passed to client-side callbacks (sampling, elicitation, list_roots) when the server sends requests
to the client.

Attributes:
    request_id: The unique identifier for this request.
    meta: Optional metadata associated with the request.
    session: The client session handling this request.
"""
