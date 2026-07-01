# Prompts

A **prompt** is a message template the user picks.

Tools are for the model. A prompt is the opposite: the user chooses one from a menu in their client (a slash command, a button), fills in its arguments, and the rendered messages go into the conversation as if they had typed them.

You declare one by putting `@mcp.prompt()` on a function that returns the text.

## Your first prompt

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

The SDK reads the same three things it read from your tools:

* The **name** is the function name: `review_code`.
* The **description** the client shows is the docstring: `Review a piece of code.`
* The **arguments** come from the parameters. `code` has no default, so it's required.

That is what a client gets back from `prompts/list`:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

There is no JSON Schema here. Prompt arguments are a flat list of **named string values**: a form a person fills in, not a payload a model constructs.

### Rendering it

The client renders the template with `prompts/get`, passing the arguments. Your function runs and the `str` you return becomes **one user message**:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

That is the entire life of a prompt: listed by name, rendered on demand, dropped into the chat.

!!! check
    `required` is enforced before your function runs. Render `review_code` without `code` and the
    request itself fails with a JSON-RPC error (code `-32603`):

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    There is no tool-style error result to hand back to a model, because no model is in the loop:
    the call raises. The reason (`Missing required arguments: {'code'}`) lands in your server's log.

### Try it

Run the server with the MCP Inspector:

```console
uv run mcp dev server.py
```

Open the **Prompts** tab and select `review_code`. The Inspector draws a form with one required `code` field. Fill it in, render it, and you get back exactly the user message above.

## More than one message

A code review is one message. A debugging session is a conversation, and a prompt can seed the whole thing.

Return a list of messages instead of a `str`:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` and `AssistantMessage` come from `mcp.server.mcpserver.prompts.base`. Hand them a `str` and they wrap it in `TextContent` for you. The role is the class name.
* `Message` is their common base. Use it as the return annotation.

Rendering `debug_error` now produces three messages, in order:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Notice the last one. Pre-filling an `assistant` turn is how you steer the model's *next* reply without making the user type the steering themselves.

## Titles and argument descriptions

`review_code` is a function name, not a label. Give the client something better to put on the button, and describe each argument so the form explains itself:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` is the human-readable name, exactly like a tool's `title`.
* `Annotated[str, Field(description=...)]` is the same pattern you used in **[Tools](tools.md)**. Here the description lands on the argument instead of in a schema.
* `language` has a default, so it stops being required.

The `prompts/list` entry now carries everything a client needs to draw a good form:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    If you have read **[Tools](tools.md)**, you already know everything on this page. Same decorator, same
    docstring-as-description, same `Annotated`/`Field`. The only things that change are who
    triggers it (the user) and where the result goes (into the conversation).

## Recap

* `@mcp.prompt()` on a function makes it a prompt. Name from the function, description from the docstring.
* Prompts are **user-controlled**: the client lists them, the user picks one and fills in the arguments.
* Arguments are a flat list of named strings (no schema). A parameter with a default is optional.
* Return a `str` and it becomes one user message. Return a list of `UserMessage` / `AssistantMessage` to seed a multi-turn conversation.
* `title=` and `Field(description=...)` are what a client puts in its UI.
* A missing required argument fails the whole request. There is no per-prompt error result.

Next up: server-side autocomplete for a prompt's (or a resource template's) arguments, in **[Completions](completions.md)**.
