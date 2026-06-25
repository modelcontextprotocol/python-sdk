# Elicitation

A tool that is halfway through its job and missing one answer doesn't have to fail.

**Elicitation** lets it ask. In the middle of a tool call the server sends the client a question, the client puts it to the user, and the answer comes back into the same function call.

There are two modes:

* **Form mode** — you need a value: a confirmation, a date, a quantity. You describe the fields, the client renders the form.
* **URL mode** — you need the user to go somewhere else: an OAuth consent screen, a payment page. Nothing they do there passes through the protocol.

## Ask with a form

`ctx.elicit()` takes a message and a Pydantic model:

```python title="server.py" hl_lines="9-11 20-23"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* The **`Context`** parameter is what gives you `ctx.elicit` — any tool can take one. That object has its own chapter: **The Context**.
* `AlternativeDate` is the **schema** of the answer you want.
* The tool is `async def`. It has to be — it stops in the middle and waits for a person.
* On any other date the tool returns straight away. It only asks when it has to.

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

That schema is the form. `Field(description=...)` is the label; a default pre-fills the input and makes the field optional. It's the same Pydantic-to-JSON-Schema machinery you already used for a tool's arguments in **Tools**.

!!! warning
    An elicitation schema is not as expressive as a tool's input schema: flat, primitive fields
    only — `str`, `int`, `float`, `bool`, or a `Literal` of strings (it becomes an `enum`).
    Put a model inside the model and `ctx.elicit` raises before anything is sent to the client:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    You are interrupting a person mid-task. If the answer needs nesting, it should have been an
    argument to the tool.

### The three answers

`result.action` tells you what the user did, and there are exactly three possibilities:

* `"accept"` — they submitted the form. `result.data` is an `AlternativeDate` instance, already validated.
* `"decline"` — they said no.
* `"cancel"` — they dismissed the question without choosing.

`result.data` only exists on `"accept"`, which is why the example checks `result.action` first. Your type checker enforces the order: after `result.action == "accept"`, `result.data` is an `AlternativeDate`; before it, there is no `.data` at all.

A refusal is not an error. The tool decides what declining means — here, no booking — and answers the model normally.

!!! tip
    The answer is validated against your model before your code sees it. A client that sends
    `"maybe"` for a `bool` doesn't corrupt your booking — the call fails with the
    `ValidationError`, your `if` never runs.

## Send the user to a URL

Some things must not go through the model or the client: credentials, card numbers, OAuth consent. For those you don't ask for data — you ask the user to go somewhere:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` takes the message, the **URL** to visit, and an `elicitation_id` you choose — any string that identifies this elicitation within your server.
* The result has an action and nothing else. `"accept"` means the user agreed to open the URL — **not** that they finished what's on the other side.
* The payment happens out of band, between the user's browser and your payment provider. No content ever comes back through MCP.

Look at the second tool. When your server learns the out-of-band flow finished — a webhook, a poll; here it's modelled as a second tool — `ctx.session.send_elicit_complete(...)` sends `notifications/elicitation/complete` with the same `elicitation_id`. That is how the client knows it can stop showing *"waiting for payment…"*. Without it, the client can only guess.

## The client side

Servers ask. Clients answer by passing an **`elicitation_callback`** to `Client(...)`:

```python title="client.py" hl_lines="7-8 19"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* One callback handles both modes. `params` is a union of `ElicitRequestFormParams` and `ElicitRequestURLParams` — `isinstance` is the branch.
* For a URL, you show `params.url` to the user and return the action they chose. Never any `content`.
* For a form, a real application renders `params.requested_schema` and returns the user's input as `content`. This one always says yes with a canned answer — which is exactly the callback you want in a test.
* Passing the callback is also the **capability declaration**: it's how the server learns this client can be asked. The other things a client can answer for a server live in **Client callbacks**.

!!! info
    Elicitation is a request from the *server* to the *client*, and those only exist on a
    classic-handshake session — which is why this client passes `mode="legacy"`.
    On a **2026-07-28** connection a tool asks by *returning* the question from the call
    instead; that flow is **Multi-round-trip requests**.

### Check it

Start `server.py` on Streamable HTTP — **Running your server** has the one-liner — then run the client's `main()` and ask `book_table` for Christmas day.

The callback prints the question it was sent:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

It answers with `{"accept_alternative": True, "date": "2025-12-27"}`, and the tool — which has been waiting inside `await ctx.elicit(...)` this whole time — finishes the booking:

```text
Booked a table for 2 on 2025-12-27.
```

Call `pay_deposit` and the same callback takes the other branch: it prints the payment link and the tool comes back with *"Complete the payment in your browser."* One round trip, mid-call, in both directions.

!!! check
    Now remove `elicitation_callback=` from the `Client` and call `book_table` for Christmas day
    again. The whole call fails with a protocol error:

    ```text
    Elicitation not supported
    ```

    A client that registered no callback never declared the `elicitation` capability, so there is
    nobody to ask. Your tool didn't get a `"decline"` — it got an exception. Design for it: every
    elicitation needs a sensible answer to "what if I can't ask?".

## Recap

* `await ctx.elicit(message, schema=Model)` asks mid-call; your tool resumes with the answer.
* The schema is a flat Pydantic model — primitive fields only, validated on the way back.
* `result.action` is `"accept"`, `"decline"` or `"cancel"`; `result.data` exists only on accept.
* `await ctx.elicit_url(message, url, elicitation_id)` is for everything that must not pass through the model; `ctx.session.send_elicit_complete(elicitation_id)` says the out-of-band part is done.
* The client answers with one `elicitation_callback`, branching on the params type — and registering it is what declares the capability.

A tool that can ask is good. A tool that says how far along it is — **Progress** — is next.
