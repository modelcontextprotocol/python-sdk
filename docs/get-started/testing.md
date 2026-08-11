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
    These docs assume you already know [`pytest`](https://docs.pytest.org/en/stable/).

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) is what the test below
    uses to assert on the whole result object in one line. It records the output of a test as the
    `snapshot(...)` literal you see. If you'd rather not use it, drop the import and assert on the
    fields you care about (`result.content[0].text == "3"`) like in any other test.

Now the test:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

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
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
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

An exception inside one of **your `@mcp.tool()` functions** is not a protocol failure. It becomes a
normal result with `is_error=True`, and the model reads the message. `raise_exceptions` doesn't
change that: with or without it, `call_tool` returns the same `is_error=True` result. There's a
whole page on it: **[Handling errors](../servers/handling-errors.md)**.

An **unexpected exception** that escapes a request handler as a bare Python exception is
different. On an in-memory `Client(server)` connection the SDK still turns that into an
`MCPError` (`-32603`) — the call raises; it does not become an `is_error` result — but by default
it sanitises the message to `"Internal server error"` and drops the original exception. You should
never leak a traceback to a remote caller. In a test that is exactly what you *don't* want.

`raise_exceptions=True` keeps the `MCPError`, but puts `str(original)` in the message and chains
the original as `__cause__`. Catch it *inside* the `async with` so anyio does not wrap it in an
`ExceptionGroup` (**[Troubleshooting](../troubleshooting.md)**):

```python title="test_buggy_handler.py"
import pytest
from mcp import Client, MCPError
from mcp.types import INTERNAL_ERROR

from server import server  # a low-level Server whose handler can KeyError


@pytest.mark.anyio
async def test_missing_argument_surfaces_the_real_key_error():
    async with Client(server, raise_exceptions=True) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("search_books", {"query": "dune"})  # no limit
    assert exc_info.value.error.code == INTERNAL_ERROR
    assert isinstance(exc_info.value.__cause__, KeyError)
```

The server that makes that failure visible is a low-level `Server` (it does not validate
`input_schema` before calling you):

```python title="server.py"
--8<-- "docs_src/testing/tutorial002.py"
```

Without the flag, the same call raises `MCPError: Internal server error` with no `__cause__`.
With a high-level `MCPServer`, most handler failures are already converted into tool
`is_error` results or intentional `MCPError`s before this flag can act — so the difference shows
up mainly for unmapped crashes (and for low-level `Server` handlers).

Leave it on in tests that use the in-memory client. It is ignored for `Client("https://...")`
and for a user-supplied `Transport`: those paths never see the flag.

## In-process by default

!!! note
    `Client(mcp)` connects in-process and is **era-neutral** by default: it probes the server and
    picks the appropriate protocol path. Pin `mode="legacy"` if your test exercises legacy-specific
    semantics (sampling or elicitation push, `message_handler`), and drop `raise_exceptions=True`
    there: a legacy connection never sanitises in the first place, and the flag re-raises the
    failure inside the server task instead of in your test.

That one line is also why these docs can promise you that their examples work: every
example file is exercised by the SDK's own test suite, almost all of them through exactly this
client. You're using the same tool the SDK uses on itself.

You have a working, tested server. Putting it inside a real application (Claude Desktop, an
IDE) is **[Connect to a real host](real-host.md)**; every other way to serve it is
**[Running your server](../run/index.md)**.
