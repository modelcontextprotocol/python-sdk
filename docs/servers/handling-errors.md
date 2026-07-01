# Handling errors

A tool can fail in two ways, and the SDK treats them very differently.

Raise an ordinary exception and the **model** sees it. Raise `MCPError` and the **protocol** sees it.

This chapter is about choosing.

## An error the model can fix

Take a tool that looks something up, and let the lookup miss:

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

There is nothing MCP about those two lines. `get_author` raises a plain `ValueError`, the way any Python function would.

Call it with a title that isn't in the catalog and look at the result:

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* The request **succeeded**. There is a result; nothing was raised at the caller.
* `is_error` is `True`, and your exception's message (prefixed with the tool name) is in `content`, exactly where the model reads.
* `structured_content` is `None`. A failed call has no return value to structure.

This is a **tool error**, and it is the default for *any* exception your tool raises. It is also almost always what you want.

The model is the one calling your tool. It picked the arguments. So a tool error is a turn in the conversation: the model reads *"No book titled 'Nothing' in the catalog."*, realises it guessed the title wrong, and calls again with a better one. You wrote one `raise` and got a self-correcting agent.

!!! tip
    Never `return` an error message from a tool. A returned string has `is_error=False`, so to the
    model (and to every client UI) it looks like the tool worked and that string was the answer.
    `raise`. The flag is the signal.

## An error the model cannot fix

Now swap `ValueError` for `MCPError`.

```python title="server.py" hl_lines="1 3 15"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` is the SDK's **protocol error**. It is the one exception the tool wrapper does *not* catch: it propagates, and the whole `tools/call` request fails with a JSON-RPC error instead of a result.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* There is **no result**. No `content`, no `is_error`: nothing for the model to read.
* The **host** application gets the error instead, the same way it would if the tool didn't exist at all.
* `code`, `message`, and `data` arrive intact. `INVALID_PARAMS` is `-32602`; `mcp_types` exports it and the other JSON-RPC error codes (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...) as constants so you never type a magic number.

!!! check
    Same lookup, same miss, but now the call *raises* on the client side instead of returning:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    The first version handed the model a sentence it could react to. This one hands it nothing.
    For `get_author` that is strictly worse, which is the point of the next section.

## Which one to raise

The two paths answer two different questions.

* **Raise any exception** for a failure of *execution*: the thing your tool tried to do didn't work. The model chose the call, so the model should see the consequence and get a chance to recover. A misspelled title, an upstream API that timed out, a row that doesn't exist: all tool errors.
* **Raise `MCPError`** when the *request itself* should be rejected: the client is missing a capability your tool depends on, the server isn't in a state to serve anyone, the caller skipped a required step. No retry from the model fixes any of those, so there is nothing to gain from handing it the message.

One question decides it: **could a smarter model have avoided this?** Yes -> ordinary exception. No -> `MCPError`.

By that test, the second version of `get_author` made the wrong choice: a better title fixes it, so the model deserved to see the message. It's there to show you the mechanism, not to recommend it.

!!! info
    `MCPError` lives at `from mcp import MCPError` and takes `code`, `message`, and an optional
    `data` payload. Whatever you put in them is what the client receives: the SDK forwards a raised
    `MCPError` verbatim instead of sanitising it.

## A resource that doesn't exist

Resources draw the same line, and ship one named exception for the common case.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` is a **template**. It matches *any* title, so "the URI is well-formed" and "the book exists" are two different questions, and only your function can answer the second one.

When it can't, raise `ResourceNotFoundError`. The SDK turns it into the protocol error the spec assigns to a missing resource: `-32602` with the requested URI in `data`, so the client knows *which* read failed.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

Notice there is no `is_error=True` half-result here. A resource read either returns contents or fails: resources have only the protocol path. Templates and everything else about resources live in **[Resources](resources.md)**.

## Errors you never raise

A bad argument never reaches your function.

Send `get_author` a `title` that isn't a string and the SDK rejects it against the input schema **before** calling you, as the same kind of `is_error=True` tool error the model can read and correct. You saw this in **[Tools](tools.md)** with `Field(le=50)`.

It means a whole class of `raise` statements you don't write: don't re-validate your own type hints.

!!! info
    Everything on this page is what a **client** sees, and the in-memory `Client` you'll write
    tests with sees exactly the same thing. Even `raise_exceptions=True` doesn't turn a tool error
    back into a traceback: by the time that flag could act, your exception is already the
    `is_error=True` result. Assert on the result. **[Testing](../get-started/testing.md)** covers the pattern.

## Recap

* Raise **any exception** in a tool -> the call returns `is_error=True` with your message in `content`. The model reads it and can retry. This is the default.
* Raise **`MCPError`** -> the call itself fails with a JSON-RPC error. The model sees nothing; the host deals with it. `code`, `message`, and `data` survive intact.
* The deciding question: *could a smarter model have avoided this?* Yes -> exception. No -> `MCPError`.
* `ResourceNotFoundError` from a resource handler -> the protocol's `-32602`, with the URI in `data`.
* Bad arguments are rejected against the schema before your function runs; you don't `raise` for those.
* `from mcp import MCPError`; the error-code constants come from `mcp_types`.

Errors handled. That is everything a server *exposes*. What every handler can read, and do back to the client while it runs, is the next section: **[Inside your handler](../handlers/index.md)**.
