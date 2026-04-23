# Postgres Knowledge Server

A production-grade MCP server backed by PostgreSQL with authorization middleware.

Demonstrates:
- **Multi-tool MCP server** — knowledge store, task queue, file routing
- **Authorization middleware** — filesystem-based identity gate (no ACL database)
- **Postgres backend** — Unix socket connection, no host/port exposure
- **Portless stdio transport** — no HTTP server, no open ports

## Architecture

```
MCP Client (Claude Code, etc.)
        │ stdio
        ▼
  sap/sap_mcp.py          ← authorization gate + FastMCP server
        │
        ├── willow_store  ← SQLite local store (30+ tools)
        ├── postgres KB   ← knowledge graph (atoms, entities)
        └── kart queue    ← sandboxed task executor
```

## Authorization Pattern

Instead of a permission database, authorization is filesystem-based:

```python
SAFE_ROOT = Path.home() / "Ashokoa" / "SAFE"

def authorized(app_id: str) -> bool:
    """Agent has a SAFE folder → it has access. No folder → denied."""
    folder = SAFE_ROOT / app_id
    return folder.exists() and (folder / "manifest").exists()
```

Grant access: `mkdir -p ~/Ashokoa/SAFE/my-agent && touch ~/Ashokoa/SAFE/my-agent/manifest`  
Revoke access: `rm -rf ~/Ashokoa/SAFE/my-agent`

The filesystem shape IS the identity. No separate ACL.

## Running

```bash
# Install
pip install mcp psycopg2-binary

# Configure Postgres (Unix socket — no host/port)
createdb myknowledge

# Run
python server.py
```

## MCP Config (Claude Code)

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "python",
      "args": ["/path/to/server.py"],
      "env": {
        "WILLOW_PG_DB": "myknowledge",
        "WILLOW_PG_USER": "myuser",
        "WILLOW_AGENT_NAME": "myagent"
      }
    }
  }
}
```
