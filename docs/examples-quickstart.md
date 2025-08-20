# Getting started

This section provides quick and simple examples to get you started with the MCP Python SDK.

These examples can be run directly with:

```bash
python server.py
```

Or test with the MCP Inspector:

```bash
uv run mcp dev server.py
```

## FastMCP quickstart

The easiest way to create an MCP server is with [`FastMCP`][mcp.server.fastmcp.FastMCP]. This example demonstrates the core concepts: tools, resources, and prompts.

```python
--8<-- "examples/snippets/servers/fastmcp_quickstart.py"
```

This example shows how to:

- Create a FastMCP server instance
- Add a tool that performs computation (`add`)
- Add a dynamic resource that provides data (`greeting://`)
- Add a prompt template for LLM interactions (`greet_user`)

## Basic server

An even simpler starting point:

```python
--8<-- "examples/fastmcp/readme-quickstart.py"
```

## Direct execution

For the simplest possible server deployment:

```python
--8<-- "examples/snippets/servers/direct_execution.py"
```

This example demonstrates:

- Minimal server setup with just a greeting tool
- Direct execution without additional configuration
- Entry point setup for standalone running
