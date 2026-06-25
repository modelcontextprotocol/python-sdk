# Tutorial - User Guide

This tutorial shows you how to use the MCP Python SDK, step by step.

Each section gradually builds on the previous ones, but it's written so you can go straight to any specific section to solve a specific problem. It also works as a future reference: you can come back to exactly the part you need.

## Run the code

All the code blocks can be copied and used directly — they are complete, working files.

To follow along, paste a block into a `server.py` and open it in the MCP Inspector:

```console
uv run mcp dev server.py
```

It is **HIGHLY encouraged** that you write (or copy) the code, edit it, and run it locally. Using it in your own editor is what really shows you the point — how little you write, the autocompletion, the type checks catching mistakes before you run anything.

## You will not be guessing

Every example in this tutorial is a complete file under [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) in the SDK's own repository, and every one of them is exercised by the SDK's test suite through an **in-memory client**:

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

You'll use this yourself in the [Testing](testing.md) chapter — it's how you test your own servers, too.

## Install the SDK

If you haven't yet, [install the SDK](../installation.md) first.

## Advanced User Guide

There is also an **Advanced User Guide** you can read after this one.

It builds on this tutorial, uses the same concepts, and teaches you the extra things: the low-level `Server`, middleware, authorization, the 2026-07-28 protocol negotiation. But you should read this first — everything in the Advanced guide assumes you know the basics.
