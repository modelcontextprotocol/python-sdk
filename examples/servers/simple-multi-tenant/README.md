# Multi-Tenant MCP Server Example

Demonstrates tenant-scoped tools, resources, and prompts using the MCP Python SDK's multi-tenancy support.

## What it shows

- **Acme** (analytics company) has `run_query` and `generate_report` tools, a `database-schema` resource, and an `analyst` prompt
- **Globex** (content company) has `publish_article` and `check_seo` tools, a `style-guide` resource, and an `editor` prompt
- Each tenant sees only their own tools, resources, and prompts — Acme cannot see Globex's tools and vice versa
- A `whoami` tool is registered under both tenants and reports the current tenant identity from `Context.tenant_id`

## Running

Start the server on the default or custom port:

```bash
uv run mcp-simple-multi-tenant --port 3000
```

The server starts a StreamableHTTP endpoint at `http://127.0.0.1:3000/mcp`.

## What each tenant sees

**Acme** (analytics):
- Tools: `run_query`, `generate_report`, `whoami`
- Resources: `data://schema` (database schema)
- Prompts: `analyst` (data analyst system prompt)

**Globex** (content):
- Tools: `publish_article`, `check_seo`, `whoami`
- Resources: `content://style-guide` (editorial style guide)
- Prompts: `editor` (content editor system prompt)

**No tenant** (unauthenticated): sees nothing — all items are tenant-scoped.

## Example: programmatic client

You can verify tenant isolation using the MCP client with in-memory transport:

```python
import asyncio

from mcp.client.session import ClientSession
from mcp.shared._context import tenant_id_var
from mcp.shared.memory import create_client_server_memory_streams

from mcp_simple_multi_tenant.server import create_server


async def main():
    server = create_server()
    actual = server._lowlevel_server

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        import anyio

        async with anyio.create_task_group() as tg:
            # Set tenant context for the server side
            async def run_server():
                token = tenant_id_var.set("acme")
                try:
                    await actual.run(
                        server_read,
                        server_write,
                        actual.create_initialization_options(),
                    )
                finally:
                    tenant_id_var.reset(token)

            tg.start_soon(run_server)

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()

                # Acme sees only analytics tools
                tools = await session.list_tools()
                print(f"Tools: {[t.name for t in tools.tools]}")
                # → ['run_query', 'generate_report', 'whoami']

                result = await session.call_tool(
                    "run_query", {"sql": "SELECT * FROM users"}
                )
                print(f"Result: {result.content[0].text}")
                # → Query result for: SELECT * FROM users (3 rows returned)

            tg.cancel_scope.cancel()


asyncio.run(main())
```

## How tenant identity works

In a production deployment, `tenant_id` is extracted from the OAuth `AccessToken` by the `AuthContextMiddleware` and propagated through the request context automatically — no manual `tenant_id_var.set()` is needed. The in-memory example above sets it manually to simulate what the middleware does.

See the [Multi-Tenancy Guide](../../../docs/multi-tenancy.md) for the full architecture.
