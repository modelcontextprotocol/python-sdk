# Advanced

Everything an ordinary server or client needs has a topical home in the sections above.
This section is the escape hatches — the things you reach for when `MCPServer`'s
convenience layer is in the way:

* **[The low-level Server](low-level-server.md)** — the class `MCPServer` is built on.
  Hand-written schemas, `on_*` handlers, nothing checked for you, and custom JSON-RPC
  methods of your own.
* **[Pagination](pagination.md)** and **[Middleware](middleware.md)** — two things you
  can *only* do on the low-level `Server`.
* **[Extensions](extensions.md)** and **[MCP Apps](apps.md)** — the protocol's
  extension surface: compose extension packages into a server, or write your own.

A few things you might reasonably look for here live where you'd actually use them
instead:

* **Authorization** is under **[Running your server](../run/index.md)** — you protect a
  server where you deploy it.
* **OAuth**, **identity assertion**, connecting to **multiple servers**, and the
  response **cache** are all under **[Clients](../client/index.md)**.
* **Multi-round-trip requests** and **Subscriptions** are under
  **[Inside your handler](../handlers/index.md)** — both are things a handler *does*.
* **URI templates** is under **[Servers](../servers/index.md)**, next to Resources.
* **[Protocol versions](../protocol-versions.md)** and
  **[Deprecated features](../deprecated.md)** each have their own top-level page.

If you're not sure whether you need this section, you don't.
