# Inside your handler

A handler's arguments come from the client. Everything *else* it can read, and
everything it can do while it runs, is here.

What it can read:

* **[The Context](../tutorial/context.md)** — the one extra parameter any handler can
  ask for: the live request, its headers, its session, and most of the verbs below.
* **[Dependencies](../tutorial/dependencies.md)** — parameters the model never sees,
  filled in by your own functions with `Resolve`.
* **[Lifespan](../tutorial/lifespan.md)** — state your server builds once at startup,
  and how a handler reaches it through the `Context`.

What it can do while it runs:

* Ask the user for more input — **[Elicitation](../tutorial/elicitation.md)**, and
  **[Multi-round-trip requests](../advanced/multi-round-trip.md)**, the 2026-07-28
  pattern that carries it.
* Report **[Progress](../tutorial/progress.md)** on something slow.
* Write logs — to standard error, for whoever operates the server — with
  **[Logging](../tutorial/logging.md)**.
* Tell subscribed clients that something changed —
  **[Subscriptions](../advanced/subscriptions.md)**.

If you haven't registered a handler yet, start with
**[Tools](../tutorial/tools.md)** — every page here assumes you have one.
