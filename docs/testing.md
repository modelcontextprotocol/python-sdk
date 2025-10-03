# Testing MCP Servers

If you call yourself a developer, you will want to test your MCP server.
The Python SDK offers the `create_connected_server_and_client_session` function to create a session
using an in-memory transport. I know, I know, the name is too long... We are working on improving it.

Anyway, let's assume you have a simple server with a single tool:

```python title="server.py"
from mcp.server import FastMCP

app = FastMCP("Calculator")

@app.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""  # (1)!
    return a + b
```

1. The docstring is automatically added as the description of the tool.

To run the below test, you'll need to install the following dependencies:

=== "pip"
    ```bash
    pip install inline-snapshot pytest
    ```

=== "uv"
    ```bash
    uv add inline-snapshot pytest
    ```

!!! info
    I think [`pytest`](https://docs.pytest.org/en/stable/) is a pretty standard testing framework,
    so I won't go into details here.

    The [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) is a library that allows
    you to take snapshots of the output of your tests. Which makes it easier to create tests for your
    server - you don't need to use it, but we are spreading the word for best practices.

```python title="test_server.py"
from collections.abc import AsyncGenerator

import pytest
from inline_snapshot import snapshot
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent

from server import app


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client_session() -> AsyncGenerator[ClientSession]:
    async with create_connected_server_and_client_session(app, raise_exceptions=True) as _session:
        yield _session


@pytest.mark.anyio
async def test_call_add_tool(client_session: ClientSession):
    result = await client_session.call_tool("add", {"a": 1, "b": 2})
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structuredContent={"result": 3},
        )
    )
```

1. If you are using `trio`, you should set `"trio"` as the `anyio_backend`. Check more information in the [anyio documentation](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on).

There you go! You can now extend your tests to cover more scenarios.
