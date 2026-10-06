from dataclasses import dataclass

from pydantic import AnyHttpUrl

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext

RESOURCE = "http://127.0.0.1:8000/mcp"
PERMISSION_DENIED = 1  # Application-defined; MCP has no standard permission-denied code.
TOOL_SCOPES = {"notes_read": "notes:read", "notes_update": "notes:write"}

# Fake tokens for a local demonstration only. Never deploy this verifier.
KNOWN_TOKENS = {
    "reader-token": AccessToken(
        token="reader-token",
        client_id="demo",
        subject="alice",
        scopes=["notes:read"],
        resource=RESOURCE,
        claims={"tenant_id": "tenant-a"},
    ),
    "writer-token": AccessToken(
        token="writer-token",
        client_id="demo",
        subject="alice",
        scopes=["notes:read", "notes:write"],
        resource=RESOURCE,
        claims={"tenant_id": "tenant-a"},
    ),
    "other-tenant-token": AccessToken(
        token="other-tenant-token",
        client_id="demo",
        subject="bob",
        scopes=["notes:read"],
        resource=RESOURCE,
        claims={"tenant_id": "tenant-b"},
    ),
}


class StaticTokenVerifier(TokenVerifier):
    """Look up fake tokens; a production verifier must validate issuer and signature."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return trusted claims only for a recognized demonstration token."""
        return KNOWN_TOKENS.get(token)


def authorize_tool(name: str) -> str:
    """Return the trusted tenant for an allowed operation.

    Raises:
        MCPError: If identity, operation scope or tenant context is missing.
    """
    token = get_access_token()
    scope = TOOL_SCOPES.get(name)
    tenant = (token.claims or {}).get("tenant_id") if token is not None else None
    if token is None or scope is None or scope not in token.scopes or not isinstance(tenant, str) or not tenant:
        raise MCPError(code=PERMISSION_DENIED, message="Operation not permitted.")
    return tenant


async def tool_permissions(ctx: ServerRequestContext, call_next: CallNext) -> HandlerResult:
    """Filter discovery and independently gate tool calls before dispatch.

    Raises:
        MCPError: If the caller cannot discover tools or execute the named operation.
    """
    if ctx.method == "tools/call":
        name = (ctx.params or {}).get("name")
        # Params are raw here; resource decisions belong in the validated handler.
        authorize_tool(name if isinstance(name, str) else "")
    result = await call_next(ctx)
    if ctx.method == "tools/list":
        token = get_access_token()
        if token is None:
            raise MCPError(code=PERMISSION_DENIED, message="Operation not permitted.")
        if not isinstance(result, dict):
            raise RuntimeError("Expected the completed tools/list response")
        # Preserve the response envelope, including the SDK's serverInfo metadata.
        result = {
            **result,
            "tools": [tool for tool in result["tools"] if TOOL_SCOPES.get(tool["name"]) in token.scopes],
        }
    return result


@dataclass
class Note:
    """Server-owned note data; callers cannot choose its tenant."""

    tenant_id: str
    text: str


def create_server() -> MCPServer:
    """Build a local demonstration with isolated in-memory note data."""
    notes = {
        "note-1": Note(tenant_id="tenant-a", text="Ship the release"),
        "note-2": Note(tenant_id="tenant-b", text="Private tenant B note"),
    }
    server = MCPServer(
        "Notes",
        token_verifier=StaticTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl("https://auth.example.com"),
            resource_server_url=AnyHttpUrl(RESOURCE),
            required_scopes=[],  # Operation scopes are checked separately.
            validate_token_resource=True,
        ),
        middleware=[tool_permissions],
    )

    def authorized_note(name: str, note_id: str) -> Note:
        tenant = authorize_tool(name)
        note = notes.get(note_id)
        if note is None or note.tenant_id != tenant:
            # The same denial avoids revealing whether another tenant's note exists.
            raise MCPError(code=PERMISSION_DENIED, message="Operation not permitted.")
        return note

    @server.tool()
    def notes_read(note_id: str) -> str:
        """Read a note by ID in the authenticated tenant; requires notes:read.

        Args:
            note_id: ID of the note to read. Tenant identity comes from the verified token.

        Raises:
            MCPError: If scope or ownership does not permit access.
        """
        return authorized_note("notes_read", note_id).text

    @server.tool()
    def notes_update(note_id: str, text: str) -> str:
        """Replace a note's text in the authenticated tenant; requires notes:write.

        Args:
            note_id: ID of the note to update. Tenant identity comes from the verified token.
            text: New text replacing the note's current contents.

        Raises:
            MCPError: If scope or ownership does not permit access.
        """
        note = authorized_note("notes_update", note_id)
        note.text = text
        return note.text

    return server


mcp = create_server()
