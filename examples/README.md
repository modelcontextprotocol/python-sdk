# Python SDK Examples

Examples are now single self-contained Python scripts that declare their dependencies inline using PEP 723 metadata. You can run them directly with uv without creating a virtualenv or installing anything globally.

Run any example like this:

```bash
uv run examples/<group>/<script>.py [args]
```

For example:

```bash
# Servers
uv run examples/servers/simple_tool.py --transport stdio
uv run examples/servers/simple_prompt.py --transport sse --port 8000
uv run examples/servers/simple_task.py --port 8000
uv run examples/servers/simple_task_interactive.py --port 8000
uv run examples/servers/simple_resource.py --transport stdio
uv run examples/servers/sse_polling_demo.py --port 3000
uv run examples/servers/simple_pagination.py --transport stdio
uv run examples/servers/simple_streamablehttp.py --port 3000
uv run examples/servers/simple_streamablehttp_stateless.py --port 3000
uv run examples/servers/structured_output_lowlevel.py
uv run examples/servers/everything_server.py --port 3001
uv run examples/servers/simple_auth_rs.py --port 8001 --auth-server http://localhost:9000
uv run examples/servers/simple_auth_as.py --port 9000

# Clients
uv run examples/clients/simple_task_client.py --url http://localhost:8000/mcp
uv run examples/clients/sse_polling_client.py --url http://localhost:3000/mcp
uv run examples/clients/simple_auth_client.py
uv run examples/clients/simple_task_interactive_client.py
uv run examples/clients/conformance_auth_client.py auth/authorization-code http://localhost:3001/mcp
uv run examples/clients/simple_chatbot.py
```

Notes:
- The scripts embed their dependencies in a header block starting with `# /// script`.
- Some servers support `--transport sse` which requires Starlette and Uvicorn; these are already included in the script metadata.
- The previous per-example `pyproject.toml` files and packages remain for now; we can remove them once you confirm the new workflow.

See the [servers repository](https://github.com/modelcontextprotocol/servers) for real-world servers.
