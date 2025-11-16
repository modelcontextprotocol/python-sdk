# Code Examples

This page demonstrates various MCP SDK examples using the snippet feature.

## FastMCP Quickstart

Here's a complete quickstart example showing how to create a server with tools, resources, and prompts:

```python title="fastmcp_quickstart.py"
--8<-- "servers/fastmcp_quickstart.py"
```

## Basic Tool Example

This example shows how to define simple tools:

```python title="basic_tool.py"
--8<-- "servers/basic_tool.py"
```

## Usage

To run any of these examples:

1. Navigate to the `examples/snippets` directory
2. Run the server using `uv run mcp dev <filename>`

For example:
```bash
cd examples/snippets
uv run mcp dev servers/basic_tool.py
```
