# Elicitation

A tool that is halfway through its job and missing one answer doesn't have to fail.

**Elicitation** lets it ask. In the middle of a tool call the user gets a question, and their answer comes back into the same function call.

There are two modes:

* **Form mode**: you need a value (a confirmation, a date, a quantity). You describe the fields, the client renders the form.
* **URL mode**: you need the user to go somewhere else (an OAuth consent screen, a payment page). Nothing they do there passes through the protocol.

And there are two ways to ask. The one to reach for is a **resolver**: you hang the question on a parameter, and the SDK asks - on any connection, whatever protocol era the client speaks. The direct way, `await ctx.elicit(...)`, is a request from the *server* to the *client*, a channel that only exists for a client on a legacy connection (spec version 2025-11-25 or earlier). Both are on this page; start with the resolver.

## Ask with a resolver

A question that gates the whole tool - *are you sure? which of the three matching accounts?* - can be lifted out of the tool body into a **resolver**, and the framework asks it for you.

A parameter annotated `Annotated[T, Resolve(fn)]` is filled by running `fn` before the tool body. The resolver returns the value directly when it already knows it, or returns `Elicit(...)` to have the framework ask:

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` reads the tool's own `path` argument by name, lists the folder, and **only elicits when it must** - an empty folder resolves to `Confirm(ok=True)` with no round-trip to the client.
* `delete_folder` annotates `ElicitationResult[Confirm]`, so the framework injects the whole outcome and the tool `match`es every case: accept-and-confirm, accept-but-keep (`ok=False`), decline, cancel.
* The `confirm` parameter never appears in the tool's input schema - the client supplies `path`, the resolver supplies `confirm`.

Annotate the unwrapped model (`Annotated[Confirm, Resolve(confirm_delete)]`) instead when the tool doesn't need to branch: it receives the model on accept and the call aborts with an error on decline or cancel.

A resolver works on **every** connection. For a client on a legacy connection the SDK sends it the question directly; on a **2026-07-28** connection the SDK *returns* the question from the call, and the client's next attempt carries the answer. Your resolver never knows the difference; what happens underneath is **[Multi-round-trip requests](multi-round-trip.md)**.

Asking is only one thing a resolver can do. The general mechanism - dependencies that compute without asking, dependencies of dependencies, what the model can and cannot supply - is the **[Dependencies](dependencies.md)** page.

## Ask from inside the tool

A tool can also stop in the middle of its own body and ask.

!!! warning
    `ctx.elicit()` and `ctx.elicit_url()` are requests from the *server* to the *client* - a
    channel that only exists for a client on a legacy connection (spec version **2025-11-25**
    or earlier). On a **2026-07-28** connection there are no server-initiated requests, so
    these calls fail. A resolver works on both. **[Protocol versions](../protocol-versions.md)**
    has the whole story.

`await ctx.elicit()` takes a message and a Pydantic model:

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* The **`Context`** parameter is what gives you `ctx.elicit`; any tool can take one. That object has its own page: **[The Context](context.md)**.
* `AlternativeDate` is the **schema** of the answer you want.
* The tool is `async def`. It has to be: it stops in the middle and waits for a person.
* On any other date the tool returns straight away. It only asks when it has to.
* The date the user accepts goes back through `book_table` itself. An answer is input like any other: an alternative that is also fully booked gets asked about again, not confirmed blind.

### What the client receives

The client gets your message and, next to it, a JSON Schema generated from the model:

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

That schema is the form. `Field(description=...)` is the label; a default pre-fills the input and makes the field optional. It's the same Pydantic-to-JSON-Schema machinery **[Tools](../servers/tools.md)** describes for a tool's arguments.

!!! warning
    An elicitation schema is not as expressive as a tool's input schema. Flat, primitive fields
    only: `str`, `int`, `float`, `bool`, or a `Literal` of strings (it becomes an `enum`).
    Put a model inside the model and `ctx.elicit` raises before anything is sent to the client:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    You are interrupting a person mid-task. If the answer needs nesting, it should have been an
    argument to the tool.

### The three answers

`result.action` tells you what the user did, and there are exactly three possibilities:

* `"accept"`: they submitted the form. `result.data` is an `AlternativeDate` instance, already validated.
* `"decline"`: they said no.
* `"cancel"`: they dismissed the question without choosing.

`result.data` only exists on `"accept"`, which is why the example checks `result.action` first. Your type checker enforces the order: after `result.action == "accept"`, `result.data` is an `AlternativeDate`; before it, there is no `.data` at all.

A refusal is not an error. The tool decides what declining means (here, no booking) and answers the model normally.

!!! tip
    The answer is validated against your model before your code sees it. A client that sends
    `"maybe"` for a `bool` doesn't corrupt your booking: the call fails with a
    schema-mismatch error, your `if` never runs.

## Send the user to a URL

Some things must not go through the model or the client: credentials, card numbers, OAuth consent. For those you don't ask for data; you ask the user to go somewhere:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` takes the message, the **URL** to visit, and an `elicitation_id` you choose: any string that identifies this elicitation within your server.
* The result has an action and nothing else. `"accept"` means the user agreed to open the URL, **not** that they finished what's on the other side.
* The payment happens out of band, between the user's browser and your payment provider. No content ever comes back through MCP.

Look at the second tool. When your server learns the out-of-band flow finished (a webhook, a poll; here it's modelled as a second tool), `ctx.session.send_elicit_complete(...)` sends `notifications/elicitation/complete` with the same `elicitation_id`. That is how the client knows it can stop showing *"waiting for payment..."*. Without it, the client can only guess.

## Ask only in a mode the client supports

A client can declare one mode without the other - a terminal that renders a form but has no browser to open a URL, or a kiosk that can only open a URL. `ctx.session.check_client_capability` reads the `form` / `url` sub-capabilities, so a tool can pick a mode the client actually supports before it asks:

```python
from mcp_types import ClientCapabilities, ElicitationCapability, FormElicitationCapability


async def book_table(ctx: Context) -> str:
    wants_form = ClientCapabilities(elicitation=ElicitationCapability(form=FormElicitationCapability()))
    if not ctx.session.check_client_capability(wants_form):
        return "This client can't render a form; send a URL or return a default instead."
    result = await ctx.elicit("Which date?", schema=AlternativeDate)
    return "booked" if result.action == "accept" else "no change"
```

A bare `ElicitationCapability()` (no mode set) matches any client that supports elicitation at all, so name a mode only when you need that specific one. This is the same *"what if I can't ask?"* design the client-side check below calls out - now decided per mode.

## The client side

Servers ask. Clients answer by passing an **`elicitation_callback`** to `Client(...)`:

```python title="client.py" hl_lines="7-8 19"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* One callback handles both modes. `params` is a union of `ElicitRequestFormParams` and `ElicitRequestURLParams`; `isinstance` is the branch.
* For a URL, you show `params.url` to the user and return the action they chose. Never any `content`.
* For a form, a real application renders `params.requested_schema` and returns the user's input as `content`. This one always says yes with a canned answer, which is exactly the callback you want in a test.
* Passing the callback is also the **capability declaration**: it's how the server learns this client can be asked. The other things a client can answer for a server live in **[Client callbacks](../client/callbacks.md)**.

!!! info
    Elicitation is a request from the *server* to the *client*, and those only exist on a
    classic-handshake session, which is why this client passes `mode="legacy"`.
    On a **2026-07-28** connection a tool asks by *returning* the question from the call
    instead; that flow is **[Multi-round-trip requests](multi-round-trip.md)**.

### Try it

Start the `ctx.elicit` form-mode `server.py` (the `book_table` one) on Streamable HTTP (**[Running your server](../run/index.md)** has the one-liner), then run the client's `main()` and ask `book_table` for Christmas day.

The callback prints the question it was sent:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

It answers with `{"accept_alternative": True, "date": "2025-12-27"}`, and the tool, which has been waiting inside `await ctx.elicit(...)` this whole time, finishes the booking:

```text
Booked a table for 2 on 2025-12-27.
```

Now swap in the URL-mode `server.py` and point the same `main()` at `pay_deposit`: the same callback takes the other branch, prints the payment link, and the tool comes back with *"Complete the payment in your browser."* One round trip, mid-call, in both directions.

!!! check
    Now remove `elicitation_callback=` from the `Client` and call `book_table` for Christmas day
    again. The whole call fails with a protocol error:

    ```text
    Elicitation not supported
    ```

    A client that registered no callback never declared the `elicitation` capability, so there is
    nobody to ask. Your tool didn't get a `"decline"`; it got an exception. Design for it: every
    elicitation needs a sensible answer to "what if I can't ask?".

## Recap

* A parameter annotated `Annotated[T, Resolve(fn)]` is filled by a resolver, which returns `Elicit(...)` when it has to ask. It works on every connection.
* The schema is a flat Pydantic model: primitive fields only, validated on the way back.
* `result.action` is `"accept"`, `"decline"` or `"cancel"`; `result.data` exists only on accept.
* `await ctx.elicit(message, schema=Model)` asks from inside the tool body, and `await ctx.elicit_url(message, url, elicitation_id)` is for everything that must not pass through the model (`ctx.session.send_elicit_complete(elicitation_id)` says the out-of-band part is done). Both are server-to-client requests: they need the client on a legacy connection.
* The client answers with one `elicitation_callback`, branching on the params type; registering it is what declares the capability.
* On a 2026-07-28 connection the server returns the question instead of pushing it; the same callback is fed by **[Multi-round-trip requests](multi-round-trip.md)**.

Everything underneath that return (the retry loop, protecting `requestState`, driving it yourself) is **[Multi-round-trip requests](multi-round-trip.md)**.
