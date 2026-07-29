# MCP Python SDK

<div align="center">

<strong>Python implementation of the Model Context Protocol (MCP)</strong>

[![PyPI][pypi-badge]][pypi-url]
[![MIT licensed][mit-badge]][mit-url]
[![Python Version][python-badge]][python-url]
[![Documentation][docs-badge]][docs-url]
[![Protocol][protocol-badge]][protocol-url]
[![Specification][spec-badge]][spec-url]

</div>

> [!NOTE]
> **This is v2 of the MCP Python SDK, the current stable release line.** It is a major rework of the SDK, both to support the [2026-07-28 MCP specification](https://modelcontextprotocol.io/specification/2026-07-28) (and every earlier revision) and to fix long-standing architectural issues. Coming from v1? See [What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/) for the tour of what changed and the [migration guide](https://py.sdk.modelcontextprotocol.io/migration/) for every breaking change.
>
> **Not ready to migrate?** v1.x lives on the [`v1.x` branch](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), continues to receive critical bug fixes and security patches, and is documented at <https://py.sdk.modelcontextprotocol.io/v1/>. Since `pip install mcp` now installs 2.x, keep a `<2` upper bound on your requirement (for example `mcp>=1.28,<2`) until you've migrated.
>
> Something rough, confusing, or broken? [Open an issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) or find us in [#python-sdk-dev on the MCP Contributors Discord](https://discord.gg/6CSzBmMkjX).

## Documentation

**The documentation lives at <https://py.sdk.modelcontextprotocol.io/>.**

It has a [Get started guide](https://py.sdk.modelcontextprotocol.io/get-started/), [What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/), the [API reference](https://py.sdk.modelcontextprotocol.io/api/mcp/), and the [migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) lets you build servers that expose data and functionality to LLM applications in a secure, standardized way. Think of it like a web API, but designed for LLM interactions. With this SDK you can:

- **Build MCP servers** that expose tools, resources, and prompts to any MCP host
- **Build MCP clients** that connect to any MCP server
- Speak every standard transport: stdio, Streamable HTTP, and SSE

## Requirements

Python 3.10+.

## Installation

```bash
uv add "mcp[cli]"      # or: pip install "mcp[cli]"
```

The `cli` extra adds the `mcp` command-line tool (`mcp dev`, `mcp run`, `mcp install`) on top of the SDK; install plain `mcp` if you don't need it. For one-off commands, `uv run --with "mcp[cli]" mcp ...` works without a project.

## A server in 15 lines

Create a `server.py`:

<!-- snippet-source docs_src/index/tutorial001.py -->
```python
from mcp.server import MCPServer

mcp = MCPServer("Demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"
```

_Full example: [docs_src/index/tutorial001.py](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs_src/index/tutorial001.py)_
<!-- /snippet-source -->

That's a complete MCP server: one tool, one templated resource. Open it in the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
uv run mcp dev server.py
```

Call `add` with `a=1`, `b=2` and you get `3` back.

Notice what you did **not** write: no JSON Schema (`a: int, b: int` _is_ the schema), no request parsing, no validation code, no protocol handling. Two type-hinted Python functions and a docstring.

[Get started](https://py.sdk.modelcontextprotocol.io/get-started/) takes it from here.

## A client in 10 lines

The same package is a full MCP **client**. `Client` connects to a URL, a stdio subprocess, a custom transport, or (for tests) straight to a server object in memory with no transport at all:

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        print(result.structured_content)  # {'result': 3}


asyncio.run(main())
```

Swap `mcp` for `"http://localhost:8000/mcp"` and the exact same code talks to a remote server.

## Contributing

We are passionate about supporting contributors of all levels of experience and would love to see you get involved in the project. See the [contributing guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/CONTRIBUTING.md) to get started.

## License

This project is licensed under the MIT License. See the [LICENSE](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) file for details.

[pypi-badge]: https://img.shields.io/pypi/v/mcp.svg
[pypi-url]: https://pypi.org/project/mcp/
[mit-badge]: https://img.shields.io/pypi/l/mcp.svg
[mit-url]: https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE
[python-badge]: https://img.shields.io/pypi/pyversions/mcp.svg
[python-url]: https://www.python.org/downloads/
[docs-badge]: https://img.shields.io/badge/docs-python--sdk-blue.svg
[docs-url]: https://py.sdk.modelcontextprotocol.io/
[protocol-badge]: https://img.shields.io/badge/protocol-modelcontextprotocol.io-blue.svg
[protocol-url]: https://modelcontextprotocol.io
[spec-badge]: https://img.shields.io/badge/spec-spec.modelcontextprotocol.io-blue.svg
[spec-url]: https://modelcontextprotocol.io/specification/latest
