# Header parameters

Most servers never need this.

A gateway or load balancer in front of your server can only route on what it can read without parsing the body. Mark a tool argument with `x-mcp-header`, and clients on the `2026-07-28` **[protocol version](../protocol-versions.md)** send its value as an HTTP header as well.

## Mark an argument

The mark is one extra key in the argument's JSON Schema. On `MCPServer`, `Field` puts it there:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* Over Streamable HTTP on `2026-07-28`, a client that has listed the tool sends `Mcp-Param-Region` alongside the body, and the server rejects a call where the two disagree.
* A client that hasn't listed the tool yet sends no header, and the call is rejected. This SDK's `Client` then lists the tools and resends the call once, so listing first only saves a round trip.
* Every other connection ignores the annotation.

Your function doesn't change: `region` still arrives as an argument.

## What can be marked

`str`, `int` and `bool` arguments. Anything else is refused when the tool is registered, with `InvalidSignature`.

That includes `str | None`, which has no single type. An optional argument needs its schema spelled out, with pydantic's `WithJsonSchema`:

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## On the low-level `Server`

There you write `input_schema` by hand, so the key goes straight in:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* Nothing checks the annotation for you: an invalid one is served, and `2026-07-28` clients leave the tool out of their listing.

## Recap

* `x-mcp-header` on a tool argument makes `2026-07-28` clients repeat it as an `Mcp-Param-*` HTTP header.
* The server rejects a call whose header and body disagree.
* Only `str`, `int` and `bool` arguments can be marked. `MCPServer` raises `InvalidSignature` for anything else.
* The low-level `Server` checks nothing, and clients drop a tool whose annotation is invalid.

The rest of the hand-written `Server` API is **[The low-level Server](low-level-server.md)**.
