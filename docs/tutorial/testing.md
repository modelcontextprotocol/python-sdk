# Testing

The Python SDK ships a `Client` class with an **in-memory transport**: pass it your server object and it connects to it directly.

No subprocess. No port. No transport at all. It's the same idea as FastAPI's `TestClient`.

## Basic usage

Let's assume you have a simple server with a single tool:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

To run the test below you'll need two extra (development) dependencies:

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    I think [`pytest`](https://docs.pytest.org/en/stable/) is a pretty standard testing framework,
    so I won't go into details here.

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) is a library that lets you
    take snapshots of the output of your tests, which makes it much easier to write tests for your
    server. You don't need to use it, but we are spreading the word for best practices.

Now the test:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp_types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. If you are using `trio`, return `"trio"` instead. See the [anyio documentation](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on) for the details.
2. The fixture yields a connected client. Every test that takes `client` gets a fresh in-memory connection to the same server.

There you go! You can now extend your tests to cover more scenarios.

## Why `raise_exceptions=True`?

Two different things can go wrong, and this flag only touches one of them.

An exception inside one of **your tools** is not a protocol failure. It becomes a normal result with
`is_error=True`, and the model reads the message. `raise_exceptions` doesn't change that — with or
without it, `call_tool` returns the same `is_error=True` result. There's a whole chapter on it:
**Handling errors**.

A failure **outside** a tool body is different. On the connection `Client(mcp)` gives you, the
server sanitises it into a generic `"Internal server error"` before the client sees it — you should
never leak the details of an unexpected crash to a remote caller. In a test that is exactly what
you *don't* want, and it is what `raise_exceptions=True` changes: your test sees the real message
instead of the sanitised one.

Leave it on in tests. It has no meaning in production code.

## In-process by default

!!! note
    `Client(mcp)` connects in-process and is **era-neutral** by default — it probes the server and
    picks the appropriate protocol path. Pin `mode="legacy"` if your test exercises legacy-specific
    semantics (sampling or elicitation push, `message_handler`) — and drop `raise_exceptions=True`
    there: a legacy connection never sanitises in the first place, and the flag re-raises the
    failure inside the server task instead of in your test.

That one line is also why the rest of this tutorial can promise you that its examples work: every
example file is exercised by the SDK's own test suite through exactly this client. You're using the
same tool the SDK uses on itself.
