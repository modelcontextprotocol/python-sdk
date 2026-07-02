# Sampling and roots

A handler can ask the connected client for two more things: a completion from the client's own model (**sampling**), and the client's workspace folders (**roots**).

Both still work, on every protocol version the SDK speaks. But read the warning before you design around them:

!!! warning "Deprecated by the 2026-07-28 specification"
    Sampling and roots are deprecated as of `2026-07-28` ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). They remain fully functional and stay in the specification for at least twelve months before becoming eligible for removal, but new implementations should not build on them. The suggested migrations: integrate directly with your LLM provider's API instead of sampling, and pass directories via tool parameters, resource URIs, or server configuration instead of roots. The SDK-wide list is in **[Deprecated features](../deprecated.md)**.

## Sampling: borrow the client's model

A resolver returns `Sample(...)` and the tool receives the completion, through the same dependency mechanism that runs `Elicit` in **[Dependencies](dependencies.md)**:

```python title="server.py" hl_lines="11-16 20"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` mirrors the `sampling/createMessage` parameters. The injected value is the client's `CreateMessageResult`; pass `tools=[...]` and it becomes a `CreateMessageResultWithTools` instead.
* The client must have declared the `sampling` capability (`sampling.tools` if you pass `tools` or `tool_choice`). If it didn't, the call fails with a `-32021` protocol error instead of sending a request the client cannot handle. A pre-2026 session with no back-channel fails with its usual no-back-channel error, since there is nothing to send on.
* At `2026-07-28` the request is delivered inside the multi-round-trip flow (**[Multi-round-trip requests](multi-round-trip.md)**); on `2025-11-25` it is a standalone request to the client. The code is the same either way, but mind the multi-round-trip rule: the request must render identically across retry rounds, so build it only from the tool's arguments and other stable data.
* Leave `include_context` alone: values other than `"none"` are themselves deprecated (SEP-2596) and need a capability almost no client declares.

## Roots: where should this go?

Roots are the folders the client says the server may operate on. They are informational guidance, not an access-control mechanism. A resolver returns `ListRoots()`:

```python title="server.py" hl_lines="11-12 16"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* The injected `ListRootsResult` carries a list of `Root`s: a `file://` URI and an optional display name.
* The gate is the same as for sampling: without a declared `roots` capability the call fails with `-32021` instead of sending the request.

On the other side of the wire, the client answers both requests with the callbacks it already has: `sampling_callback` and `list_roots_callback`, covered in **[Client callbacks](../client/callbacks.md)**.

## On 2025-era connections

`ctx.session.create_message(...)` and `ctx.session.list_roots()` still exist for code that drives the session directly. They only work where a back-channel exists (2025-era, non-stateless connections), and calling them raises a deprecation warning. The resolver markers above are the supported form: they pick the delivery from the negotiated version and don't warn.

## Recap

* Return `Sample(...)` or `ListRoots()` from a resolver; the tool receives the `CreateMessageResult` or `ListRootsResult` like any other dependency.
* The client must declare the matching capability, or the call fails with `-32021` instead of a request being sent.
* Both features are deprecated at `2026-07-28`: fully functional for now, wrong for new designs. Prefer provider APIs over sampling and explicit parameters over roots.

Reporting how far along a slow tool is: **[Progress](progress.md)**.
