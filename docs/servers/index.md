# Servers

An `MCPServer` exposes three primitives to a connected client. They differ by who
decides to use them:

* A **[tool](../tutorial/tools.md)** is an action the *model* picks and calls. This is
  the page most people want first, and
  **[Structured Output](../tutorial/structured-output.md)** is its reference companion:
  everything about the shape of what a tool returns.
* A **[resource](../tutorial/resources.md)** is read-only data the *application*
  chooses to read. **[URI templates](../advanced/uri-templates.md)** is its reference
  companion: the full addressing syntax and the path-safety rules.
* A **[prompt](../tutorial/prompts.md)** is a message template a *person* invokes by
  name, from a menu or a slash command.

Around the three primitives, the rest of what a server declares:

* **[Completions](../tutorial/completions.md)** — server-side autocomplete for prompt
  and resource-template arguments.
* **[Images, audio & icons](../tutorial/media.md)** — everything a tool can
  return besides text, and the icons a client shows next to your server.
* **[Handling errors](../tutorial/handling-errors.md)** — the difference between an
  error the model can recover from and one it must never see.

Every page here stands on its own; jump straight to the one you need. If you haven't
built a server yet, start with **[First steps](../tutorial/first-steps.md)** instead.

What happens *inside* the functions you register — the `Context`, dependency injection,
asking the user for more input mid-call — is the next section,
**[Inside your handler](../handlers/index.md)**.
