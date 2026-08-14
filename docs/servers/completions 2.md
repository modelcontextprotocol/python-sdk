# Completions

A client building a UI on top of your server wants to autocomplete argument values as the user types: language names, repository names, file paths.

**Completions** are how your server supplies those suggestions.

## Something worth completing

Completions apply to exactly two things: the arguments of a **prompt** and the parameters of a **resource template**. So start with a server that has one of each:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

Nothing here is about completions yet.

* `review_code` takes a `language`. A user shouldn't have to guess which spellings you accept.
* `github_repo` takes an `owner` and a `repo`. Free-text boxes for both make a bad form.

## The completion handler

Add **one** function decorated with `@mcp.completion()`:

```python title="server.py" hl_lines="22-30"
--8<-- "docs_src/completions/tutorial002.py"
```

* There is one handler per server. Every completion request lands here, and you branch on what's being completed.
* It must be `async def`: the SDK awaits it.
* It receives three arguments:
  * `ref`: *which* prompt or resource template, as a `PromptReference` or a `ResourceTemplateReference`. `isinstance` is how you tell them apart.
  * `argument`: `argument.name` is the argument being completed, `argument.value` is what the user has typed so far.
  * `context`: the arguments already resolved. Ignore it for now.
* You return a `Completion(values=[...])`, or `None` when you have nothing to offer.

!!! tip
    `argument.value` is the prefix the user has typed. The SDK does **not** filter for you: whatever
    you put in `values` is what the UI shows. The `startswith` is yours to write.

### Try it

Drive it with the in-memory `Client` from **[Testing](../get-started/testing.md)**. Call
`client.complete()` with `ref=PromptReference(name="review_code")` and
`argument={"name": "language", "value": "py"}`:

```python
result.completion.values  # ['python']
```

* `ref` is the same reference type your handler receives.
* `argument` is a plain dict with exactly two keys, `name` and `value`.

Send an empty `value` and you get the whole list back. `lang.startswith("")` is true for every language:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

Ask about `code` (an argument your handler doesn't recognise) and it returns `None`, which the SDK turns into an empty list:

```python
result.completion.values  # []
```

`None` means *"no suggestions"*, never an error. A UI falls back to a plain text box.

## A capability you never declared

Registering the handler is the declaration. Connect a client and look:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

You didn't list `completions` anywhere. The SDK saw the handler and declared the capability for you. Every *optional* capability works this way: the handler is the declaration. (The three primitives are not optional: `MCPServer` always declares those, handlers or not.)

!!! check
    Go back to the first `server.py` (the one with no handler) and ask it anyway. The call fails
    with a JSON-RPC error:

    ```text
    Method not found
    ```

    And `client.server_capabilities.completions` is `None`. That's the point of the capability: a
    well-behaved client checks it and never sends the request you can't answer.

## Dependent arguments

`github://repos/{owner}/{repo}` has two parameters, and the useful values for `repo` depend on which `owner` was picked first.

That's what `context` is for. It carries the arguments the user has **already resolved**:

```python title="server.py" hl_lines="9-12 35-39"
--8<-- "docs_src/completions/tutorial003.py"
```

* The new branch fires for the template's `repo` parameter.
* `context.arguments` is a `dict[str, str] | None` of the values picked so far (here, `owner`).
* No `owner` yet means no sensible suggestions, so the handler returns `None`.

The client sends those resolved values with `context_arguments=`. This time `ref` is a
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`. Ask for `repo` with an
empty `value` and pass `context_arguments={"owner": "modelcontextprotocol"}`:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

Drop `context_arguments=` and the same call returns `[]`. The handler can't know which repos to offer until it knows the owner.

!!! info
    `Completion` also takes `total=` and `has_more=`. Set them when `values` is a slice of a longer
    list, so a UI can show *"and 200 more"*. Most handlers never need them.

## Recap

* Completions are suggestions for **prompt arguments** and **resource template parameters**. Nothing else.
* `@mcp.completion()` registers the one handler. It's `async def (ref, argument, context) -> Completion | None`.
* Branch on `isinstance(ref, ...)` and on `argument.name`. Filter by `argument.value` yourself.
* `None` becomes an empty list. It is never an error.
* `context.arguments` holds the already-resolved values; the client supplies them as `context_arguments=`.
* The `completions` capability appears the moment you register the handler. Without it, the request is `Method not found`.

Suggestions help while the user is still *filling in* a prompt or template; to ask them a question in the *middle* of a tool call, you want **[Elicitation](../handlers/elicitation.md)**. Everything a tool can return besides text is **[Images, audio & icons](media.md)**.
