"""
Postgres-backed MCP server with filesystem-based authorization.

Demonstrates:
- Multi-tool MCP server (knowledge store read/write + search)
- Authorization middleware: filesystem gate, no ACL database
- Postgres backend via Unix socket (portless, no host/port exposure)
- stdio-only transport (no HTTP server)

Usage:
    Set env vars: WILLOW_PG_DB, WILLOW_PG_USER, WILLOW_SAFE_ROOT
    Grant access: mkdir -p $WILLOW_SAFE_ROOT/my-app && echo '{}' > $WILLOW_SAFE_ROOT/my-app/manifest
    Run: python -m mcp_postgres_server
"""

import json
import os
from pathlib import Path

import anyio
import click
import psycopg2
import psycopg2.extras
from mcp import types
from mcp.server import Server, ServerRequestContext

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PG_DB = os.environ.get("WILLOW_PG_DB", "knowledge")
PG_USER = os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "postgres"))
SAFE_ROOT = Path(os.environ.get("WILLOW_SAFE_ROOT", Path.home() / "SAFE"))


# ---------------------------------------------------------------------------
# Authorization gate
# ---------------------------------------------------------------------------

def authorized(app_id: str) -> bool:
    """Filesystem-based authorization: folder exists → access granted.

    No permission database. The presence of the folder IS the permission.
    Grant:  mkdir -p $SAFE_ROOT/<app_id> && touch $SAFE_ROOT/<app_id>/manifest
    Revoke: rm -rf $SAFE_ROOT/<app_id>
    """
    if not app_id or "/" in app_id or ".." in app_id:
        return False
    folder = SAFE_ROOT / app_id
    return folder.is_dir() and (folder / "manifest").exists()


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------

def get_conn():
    return psycopg2.connect(dbname=PG_DB, user=PG_USER)


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id      TEXT PRIMARY KEY,
                app_id  TEXT NOT NULL,
                title   TEXT,
                body    TEXT,
                created TIMESTAMPTZ DEFAULT now()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS knowledge_app ON knowledge(app_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS knowledge_fts ON knowledge USING gin(to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,'')))")
    conn.commit()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

TOOLS = [
    types.Tool(
        name="knowledge_put",
        title="Store Knowledge",
        description="Write a record to the knowledge base.",
        input_schema={
            "type": "object",
            "required": ["app_id", "id", "title", "body"],
            "properties": {
                "app_id": {"type": "string", "description": "Authorized app identifier"},
                "id":     {"type": "string", "description": "Unique record ID"},
                "title":  {"type": "string", "description": "Record title"},
                "body":   {"type": "string", "description": "Record content"},
            },
        },
    ),
    types.Tool(
        name="knowledge_get",
        title="Get Knowledge",
        description="Retrieve a record by ID.",
        input_schema={
            "type": "object",
            "required": ["app_id", "id"],
            "properties": {
                "app_id": {"type": "string"},
                "id":     {"type": "string"},
            },
        },
    ),
    types.Tool(
        name="knowledge_search",
        title="Search Knowledge",
        description="Full-text search across the knowledge base.",
        input_schema={
            "type": "object",
            "required": ["app_id", "query"],
            "properties": {
                "app_id": {"type": "string"},
                "query":  {"type": "string"},
                "limit":  {"type": "integer", "default": 10},
            },
        },
    ),
]


async def handle_list_tools(
    ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=TOOLS)


async def handle_call_tool(
    ctx: ServerRequestContext, params: types.CallToolRequestParams
) -> types.CallToolResult:
    args = params.arguments or {}
    app_id = args.get("app_id", "")

    if not authorized(app_id):
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Unauthorized: no SAFE folder for '{app_id}'")],
            isError=True,
        )

    try:
        conn = get_conn()
        ensure_schema(conn)

        if params.name == "knowledge_put":
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO knowledge (id, app_id, title, body) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, body=EXCLUDED.body",
                    (args["id"], app_id, args["title"], args["body"]),
                )
            conn.commit()
            result = {"id": args["id"], "action": "stored"}

        elif params.name == "knowledge_get":
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT id, title, body, created FROM knowledge WHERE id=%s AND app_id=%s",
                            (args["id"], app_id))
                row = cur.fetchone()
            result = dict(row) if row else {"error": "not_found"}

        elif params.name == "knowledge_search":
            limit = min(int(args.get("limit", 10)), 50)
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, title, created FROM knowledge"
                    " WHERE app_id=%s AND to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))"
                    "       @@ plainto_tsquery('english', %s)"
                    " LIMIT %s",
                    (app_id, args["query"], limit),
                )
                result = [dict(r) for r in cur.fetchall()]

        else:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Unknown tool: {params.name}")],
                isError=True,
            )

        conn.close()
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, default=str))]
        )

    except Exception as exc:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"Error: {exc}")],
            isError=True,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@click.command()
def main():
    """Postgres-backed MCP knowledge server (stdio transport)."""
    app = Server(
        "mcp-postgres-knowledge",
        on_list_tools=handle_list_tools,
        on_call_tool=handle_call_tool,
    )

    from mcp.server.stdio import stdio_server

    async def arun():
        async with stdio_server() as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())

    anyio.run(arun)
