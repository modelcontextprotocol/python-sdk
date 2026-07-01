# Get started

New to MCP, or new to this SDK? Start here. These pages take you from nothing to a
working, tested server: [install the SDK](installation.md), build your
[first server](first-steps.md), and [test it](testing.md) with an in-memory client.

## Run the code

All the code blocks can be copied and used directly: they are complete, working files.

To follow along, paste a block into a `server.py` and open it in the MCP Inspector:

```console
uv run mcp dev server.py
```

It is **HIGHLY encouraged** that you write (or copy) the code, edit it, and run it locally. Using it in your own editor is what really shows you the point: how little you write, the autocompletion, the type checks catching mistakes before you run anything.

## You will not be guessing

Every example in these docs is a complete file under [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) in the SDK's own repository, and every one of them is exercised by the SDK's test suite through an **in-memory client**:

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

No subprocess, no port, no transport. `Client(mcp)` connects to the server object directly.

If a change to the SDK breaks an example on one of these pages, CI goes red before the page does. The code you read here is the code that runs.

You'll use this yourself in [Testing](testing.md); it's how you test your own servers, too.

## Where to go next

Once you have a server running, the rest of these docs are a reference, not a course.
Every page stands on its own — jump straight to what you need:

* What a server exposes — tools, resources, prompts — is **[Servers](../servers/index.md)**.
* What's available inside the functions you register is **[Inside your handler](../handlers/index.md)**.
* Getting it in front of clients — stdio, HTTP, your existing FastAPI app — is **[Running your server](../run/index.md)**.
* Building the other side, an application that *uses* MCP servers, is **[Clients](../client/index.md)**.
