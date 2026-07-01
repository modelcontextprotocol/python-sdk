# First steps

On the landing page you wrote a server, ran it, and called a tool.

Now do it again, slowly, with all three things a server can expose, and the names for everything you just saw.

## Host, client, and server

Three words you'll see on every page from here on:

* A **host** is the LLM application: Claude, an IDE, an agent runtime. It's the thing the user is talking to.
* A **client** lives inside the host and speaks MCP. The host runs one client per server it's connected to.
* A **server** is what you build with this SDK. It exposes things to clients. It never talks to the model directly.

You write the server. Hosts are someone else's product. The SDK also gives you a `Client`. You'll use it to test your servers, and it shows up later in this chapter.

## The three primitives

A server exposes exactly three kinds of thing. What separates them is **who decides to use them**:

| Primitive     | Controlled by   | What it is                                          | Example                            |
|---------------|-----------------|-----------------------------------------------------|------------------------------------|
| **Tools**     | The model       | A function the model calls to take an action        | An API call, a database write      |
| **Resources** | The application | Data the host loads into the model's context        | A file's contents, an API response |
| **Prompts**   | The user        | A reusable message template the user invokes by name | A slash command, a menu entry      |

"Controlled by" is the whole point of the split. A tool runs because the **model** decided to call it. A resource is attached because the **application** decided the model needed it. A prompt runs because the **user** picked it.

!!! info
    If you've built a web API you already have most of the intuition: a **resource** is a `GET`
    (it loads data and changes nothing) and a **tool** is a `POST` (it does work and may have
    side effects). A **prompt** has no HTTP analogue; it's closer to a saved query the user runs
    by name.

## One server, all three

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Three plain functions, three decorators. Each decorator is the entire registration:

* `@mcp.tool()` makes `add` a **tool**.
* `@mcp.resource("greeting://{name}")` makes `greeting` a **resource template**: the `{name}` in the URI is the function's parameter.
* `@mcp.prompt()` makes `summarize` a **prompt**. The string it returns becomes a user message.

Everything else (the name, the description, the argument schema) the SDK reads from the function itself: its name, its docstring, its type hints. You never declared any of it separately.

!!! tip
    The two halves of the SDK have two import paths: `from mcp import Client` and
    `from mcp.server import MCPServer`. There is no `from mcp import MCPServer`.

### Try it

Run it with the MCP Inspector:

```console
uv run mcp dev server.py
```

Open the URL it prints. The Inspector has one tab per primitive; walk through them in order.

**Tools.** One entry: `add`, described as *Add two numbers.* The form has a required integer field for `a` and another for `b`. Fill them in, call it, and the result is `3`. The Inspector built that form from `a: int, b: int`. So does every other client.

**Resources.** The *Resources* list is empty. `greeting` is under **Resource Templates**, because `greeting://{name}` has a parameter: there is no single resource to list until someone supplies a `name`. Give it `World` and read it:

```text
Hello, World!
```

**Prompts.** One entry: `summarize`, with a single required `text` argument. Get it with some text and you receive one message with `role: user` and your rendered string as the content. That's all a prompt is: a function that builds messages.

The Inspector ran your server over **stdio**, one of the transports an MCP server can speak. You don't pick one yet; **[Running your server](../run/index.md)** is the chapter for that.

## Capabilities

You saw three tabs in the Inspector. How did it know there were three?

When a client connects, the server declares its **capabilities**: which families of requests it will answer. The client uses that declaration to decide what to even ask for. You never wrote it; `MCPServer` declares it for you.

Look at it yourself. The SDK's `Client` accepts the server object directly and connects to it **in memory** (no subprocess, no port):

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

That dictionary is the server's half of the handshake:

| Capability  | The client may now call                                    |
|-------------|------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                  |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                               |

`MCPServer` serves all three primitives, so all three are always declared.

Notice what isn't there. `completions` (argument autocomplete for resource templates and prompts) needs a handler you write, this server doesn't have one, so the capability is absent and a well-behaved client won't ask. That's the rule for everything optional: register the thing and the capability appears; **[Completions](../servers/completions.md)** proves it.

!!! info
    `Client(mcp)` is the same in-memory client every example in these docs is tested with, and
    it's how you'll test yours. It gets a whole page: **[Testing](testing.md)**.

## What you did not write

Look back over this page. You wrote three small Python functions. You did **not** write:

* A JSON Schema. `a: int, b: int` *is* the schema for `add`.
* A request handler. `tools/list`, `resources/read`, `prompts/get`: all served for you.
* A capability declaration. `MCPServer` made it for you.
* A line of protocol. The handshake, the version negotiation, the JSON-RPC framing: all of it happened inside `mcp dev` and `Client(mcp)`, and you never saw it.

That ratio is the whole point of the SDK.

## Recap

* A **host** is the LLM app, a **client** is its MCP-speaking half, a **server** is what you build.
* Tools are **model**-controlled, resources are **application**-controlled, prompts are **user**-controlled.
* One decorator per primitive: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Name, description, and schema come from the function.
* A URI with a `{param}` makes a resource **template**, listed separately from concrete resources.
* The server's **capabilities** are declared for you, and a client only asks for what a server declares.
* `Client(mcp)` connects to the server object in memory: your test harness from day one.

Next: **[Testing](testing.md)** — one page, one in-memory client, and you're never guessing whether it works. Then each primitive gets its own page, starting with the one the model drives: **[Tools](../servers/tools.md)**.
