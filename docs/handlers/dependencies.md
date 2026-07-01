# Dependencies

A tool's arguments come from the model. Some values never should: a price looked up from your records, a confirmation only a person can give, anything the model could get wrong by inventing it.

**Dependencies** are parameters filled by your own functions. You annotate the parameter, name the function, and the SDK calls it before your tool runs.

## Declare one

Wrap the parameter's type in `Annotated[...]` and add `Resolve(fn)`:

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` is a **resolver**: a plain function the SDK runs before `reserve_book`, whose return value becomes the `stock` argument.
* Its `title` parameter is the tool's own `title` argument, matched **by name**. The resolver sees exactly the validated value the tool body will see.
* The tool body starts from a `Stock` that already exists. No lookup code in the tool, no "what if it's missing" preamble.

!!! info
    If you've used FastAPI, this is `Depends`. Same move, same reason: the function declares what
    it needs, the framework supplies it, and the wiring lives in the type annotation.

### Invisible to the model

Here is the input schema `tools/list` reports for `reserve_book`:

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

One property. Like the `Context` in **[The Context](context.md)**, a resolved parameter is a contract between you and the SDK: `stock` is not in the schema, the model is never told about it, and a client that sends a `stock` value anyway is ignored. The resolver's value is the only one your tool can receive.

That last part is the point. A parameter the model cannot supply is a parameter the model cannot get wrong.

### Try it

Run the server with the MCP Inspector:

```console
uv run mcp dev server.py
```

The form for `reserve_book` has a single `title` field. `stock` is nowhere on it. Call it with `Dune`:

```text
Reserved 'Dune' (6 copies left).
```

The tool body never looked anything up: `check_stock` ran first, and the `Stock` it returned arrived as an argument. Try `Neuromancer` and the same resolver hands the tool a zero.

!!! tip
    You could just call `check_stock(title)` in the tool body. Declare it as a dependency when the
    value deserves more than a helper call: every tool that needs stock declares the same parameter,
    and the SDK runs the resolver at most once per call, no matter how many declare it. The next
    sections add the rest: resolvers that depend on each other, and resolvers that ask the user.

## Dependencies of dependencies

A resolver can declare its own dependencies, with the same annotation:

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` depends on `check_stock`. The SDK runs the graph in order: stock first, then the estimate, then the tool.
* Both `stock` and `delivery` ultimately need `check_stock`, but it runs **once per call**. One inventory lookup, two consumers.
* There is nothing to register. The graph *is* the annotations.

!!! check
    Don't take once-per-call on faith. Put a `print` in `check_stock` and call `order_book` from the
    Inspector: one line per call. Two consumers, one lookup.

The SDK analyses the graph when the tool is registered, not when it is called. A parameter it can't classify - not a `Context`, not a `Resolve(...)`, not a tool argument's name - and a cycle of resolvers both raise `InvalidSignature` at startup. Your server fails before a client ever connects, with the offending parameter or resolver named in the error.

A resolver's parameters resolve exactly like a tool's: another `Resolve(...)`, the tool's own arguments by name, or the `Context` - `ctx.headers`, the lifespan object, all of it.

!!! warning
    On HTTP transports the `Context` includes `ctx.headers`. Headers are **client-supplied input**,
    like any tool argument: fine for a locale or a feature flag, never an identity. Who the caller
    is comes from your authorization layer (**[Authorization](../run/authorization.md)**), not from a header anyone can set.

!!! tip
    *Once per call* means exactly that: the next `tools/call` runs `check_stock` again. A resource
    that should outlive a request - a database pool, an HTTP client - belongs in **[Lifespan](lifespan.md)**, and
    a resolver can reach it through `ctx.request_context.lifespan_context`.

## Ask when you must

A resolver doesn't have to know the answer. It can return `Elicit(message, Model)` and the SDK asks the user - the **[Elicitation](elicitation.md)** machinery, run for you:

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* In stock: `confirm_backorder` returns a `Backorder` directly. **No question, no round-trip.** The user is only interrupted when their answer matters.
* Out of stock: the SDK sends the elicitation, validates the answer against `Backorder`, and injects it. Your resolver never touches the protocol.
* The tool reads `backorder.confirm` like any other argument. Answering **no** is still an answer: the elicitation is accepted with `confirm=False`, the tool runs, and no order is placed. Asking became a precondition, not plumbing in the tool body.

And if the user won't answer at all - declines the question, or cancels it?

!!! check
    Run `order_book` for `Neuromancer` and decline the question. With the annotation written as
    `Annotated[Backorder, Resolve(...)]` the tool body never runs; the call fails with an error
    result the model can read:

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

That's the right default for a precondition: no answer, no order. When declining is an outcome your tool wants to handle - skip the backorder but still suggest another title - annotate `ElicitationResult[Backorder]` instead and the tool receives the full accept/decline/cancel outcome to branch on. **[Elicitation](elicitation.md)** shows that form, and everything else about asking: the schema rules, the three answers, the client's side of the conversation.

!!! info
    The framework picks the question's transport from the negotiated protocol version; the code
    above is identical on both. On **2026-07-28** and later the question rides inside a
    multi-round-trip `tools/call` - the server returns it, the client's `elicitation_callback`
    answers it, and the `Client` retries the call for you (**[Multi-round-trip requests](multi-round-trip.md)**). On
    **2025-11-25** and earlier it is a synchronous elicitation request mid-call. Each question is
    asked exactly once per call - a guarantee about the question, not the resolver. In the
    multi-round-trip form any resolver may run again whenever the call resumes after a question,
    so code before a `return Elicit(...)` runs on each of those rounds; the recorded answer then
    satisfies the repeated question without prompting the user again. A recorded answer is only
    ever consulted when the resolver asks; a resolver that answers *without* asking, like
    `check_stock`, always supplies its own computed value. Because each answer is matched back to
    its question, an eliciting resolver must derive its question deterministically from the
    tool's arguments and earlier answers. A per-call generated value (a `default_factory` id, a
    timestamp) is re-derived on each round and must not appear in a question the answer is meant
    to bind to. A question built from such volatile data makes every recorded answer look stale,
    so the server re-asks it on every round until the client's round limit ends the call.

## Ask the client, not the user

Elicitation is one of three questions a resolver can ask - the closed set the multi-round-trip flow allows. The other two go to the **client** rather than the user: return `Sample(...)` to run an LLM call through the client (a `sampling/createMessage` request), or `ListRoots()` to fetch the client's current roots. Neither has an accept/decline outcome - the consumer annotates the result type directly, `CreateMessageResult` (`CreateMessageResultWithTools` when the request carries tools) or `ListRootsResult`:

```python title="server.py" hl_lines="11-16 22"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* The framework routes these exactly like `Elicit`: inside the multi-round-trip `tools/call` on **2026-07-28**, over the standalone server->client request on **2025-11-25** - and on either transport it refuses with a `-32021` protocol error when the client never declared the matching capability (`sampling`, `roots`, `elicitation`; `sampling.tools` when the request carries tools).
* Everything the info box above says about questions applies unchanged: a `Sample` request is matched to its recorded result by its exact rendering, so build it deterministically from the tool's arguments and earlier answers - the client then pays for the LLM call once per tool call, not once per round. The recorded result rides `request_state` for the rest of the call, so a very large completion makes every remaining round-trip heavier.
* The standalone sampling and roots *features* are deprecated at 2026-07-28 (SEP-2577) - new servers that need the client's model ask through this carrier instead, and servers that don't should integrate with an LLM provider directly. `include_context` values other than `"none"` are themselves deprecated; avoid them.

## Recap

* `Annotated[T, Resolve(fn)]` on a tool parameter: the SDK runs `fn` and injects its return value.
* A resolved parameter is invisible to the model and cannot be supplied by a client. Values the model must not invent - prices, identities, permissions - belong here.
* A resolver's parameters are resolved the same way: the `Context`, another `Resolve(...)`, or a tool argument by name. The graph runs each resolver at most once per round, however many consumers it has; each question is asked exactly once, and any resolver may run again when a call resumes after a question.
* Bad graphs fail at registration with `InvalidSignature`, not mid-call.
* Return `Elicit(message, Model)` to ask the user, only when you have to. Unwrapped annotations abort on decline; `ElicitationResult[T]` lets the tool branch.
* Return `Sample(...)` or `ListRoots()` to ask the client - an LLM completion or the roots list, injected as the plain result.

The state your server builds once at startup, and how a handler reaches it, is the **[Lifespan](lifespan.md)** page.
