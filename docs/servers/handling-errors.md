# Handling errors

A tool can fail in two ways, and the SDK treats them very differently.

Raise `ToolError` when the **model** should see a safe, actionable message. Raise `MCPError` when the
**protocol** should see the failure. Unexpected exceptions are logged server-side and replaced with a
generic tool error.

This page is about choosing.

## An error the model can fix

Take a tool that looks something up, and let the lookup miss:

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`get_author` raises `ToolError` with the message the model is allowed to see. Use this exception for
expected, recoverable failures such as a missing catalog entry.

Call it with a title that isn't in the catalog and look at the result:

```python
result.is_error            # True
result.content             # [TextContent(text="No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* The request **succeeded**. There is a result; nothing was raised at the caller.
* `is_error` is `True`, and the `ToolError` message is in `content`, exactly where the model reads.
* `structured_content` is `None`. A failed call has no return value to structure.

This is a **tool error**. The message is explicit and safe because the tool author chose to raise
`ToolError`.

The model is the one calling your tool. It picked the arguments. So a tool error is a turn in the conversation: the model reads *"No book titled 'Nothing' in the catalog."*, realises it guessed the title wrong, and calls again with a better one. You wrote one `raise ToolError(...)` and got a self-correcting agent.

!!! warning
    If an unexpected exception escapes the tool, the SDK logs the traceback on the server and returns
    `An unexpected error occurred while executing tool <name>`. It never sends the exception value to
    the client. Use `ToolError` when the model needs a specific recovery hint.

!!! tip
    Never `return` an error message from a tool. A returned string has `is_error=False`, so to the
    model (and to every client UI) it looks like the tool worked and that string was the answer.
    `raise ToolError(...)`. The flag is the signal.

## An error the model cannot fix

Now swap `ToolError` for `MCPError`.

```python title="server.py" hl_lines="1 3 14"
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
* `code`, `message`, and `data` arrive intact. `INVALID_PARAMS` is `-32602`; `mcp.types` exports it and the other JSON-RPC error codes (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...) as constants so you never type a magic number.

!!! check
    Same lookup, same miss, but now the call *raises* on the client side instead of returning:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    The first version handed the model a sentence it could react to. This one hands it nothing.
    For `get_author` that is strictly worse, which is the point of the next section.

## Which one to raise

The two paths answer two different questions.

* **Raise `ToolError`** for an expected failure of *execution* that the model can recover from. Include only information that is safe for the client to see: a misspelled title, a row that doesn't exist, or a user-facing validation message.
* Let **unexpected exceptions** propagate when the details are for server operators. The SDK logs the traceback and returns a generic `is_error=True` result.
* **Raise `MCPError`** when the *request itself* should be rejected: the client is missing a capability your tool depends on, the server isn't in a state to serve anyone, the caller skipped a required step. No retry from the model fixes any of those, so there is nothing to gain from handing it the message.

One question decides it: **does the model need a safe recovery hint?** Yes -> `ToolError`. No, because
the failure is unexpected or internal -> let the original exception be logged and sanitized. If the
request itself is invalid or unsupported -> `MCPError`.

By that test, `get_author` uses `ToolError`: a better title fixes the problem, so the model deserves
to see the message.

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

Send `get_author` a `title` that isn't a string and the SDK rejects it against the input schema **before** calling you, returning a generic `is_error=True` tool result. The validation details stay in the server log while the model can use the advertised schema to correct its arguments. **[Tools](tools.md)** shows the same rejection with a `Field(le=50)` constraint.

It means a whole class of `raise` statements you don't write: don't re-validate your own type hints.

!!! info
    Everything on this page is what a **client** sees, and the in-memory `Client` you'll write
    tests with sees exactly the same thing. Even `raise_exceptions=True` doesn't turn a tool error
    back into a traceback: by the time that flag could act, your exception is already the
    `is_error=True` result. Assert on the result. **[Testing](../get-started/testing.md)** covers the pattern.

## Recap

* Raise **`ToolError`** in a tool -> the call returns `is_error=True` with your safe message in `content`. The model reads it and can retry.
* Let an **unexpected exception** escape -> the server logs the traceback and the call returns `is_error=True` with a generic message.
* Raise **`MCPError`** -> the call itself fails with a JSON-RPC error. The model sees nothing; the host deals with it. `code`, `message`, and `data` survive intact.
* The deciding question: *does the model need a safe recovery hint?* Yes -> `ToolError`. No -> let the SDK sanitize the unexpected error, or raise `MCPError` if the request itself should fail.
* `ResourceNotFoundError` from a resource handler -> the protocol's `-32602`, with the URI in `data`.
* Bad arguments are rejected against the schema before your function runs; you don't `raise` for those.
* `from mcp import MCPError`; the error-code constants come from `mcp.types`.

Errors handled. That is everything a server *exposes*. What every handler can read, and do back to the client while it runs, is the next section: **[Inside your handler](../handlers/index.md)**.

The exact text of the SDK errors you are most likely to meet, what each means, and the one-move fix for each is **[Troubleshooting](../troubleshooting.md)**.
