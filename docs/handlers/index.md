# Inside your handler

A handler's arguments come from the client. Everything *else* it can read, and
everything it can do while it runs, is here.

What it can read:

* **[The Context](context.md)** — the one extra parameter any handler can
  ask for: the live request, its headers, its session, and the progress and
  change-notification verbs.
* **[Dependencies](dependencies.md)** — parameters the model never sees,
  filled in by your own functions with `Resolve`.
* **[Lifespan](lifespan.md)** — state your server builds once at startup,
  and how a handler reaches it through the `Context`.

What it can do while it runs:

* Ask the user for more input — **[Elicitation](elicitation.md)**, and
  **[Multi-round-trip requests](multi-round-trip.md)**, the 2026-07-28
  pattern that carries it.
* Report **[Progress](progress.md)** on something slow.
* Write logs — to standard error, for whoever operates the server — with
  **[Logging](logging.md)**.
* Tell subscribed clients that something changed —
  **[Subscriptions](subscriptions.md)**.

If you haven't registered a handler yet, start with
**[Tools](../servers/tools.md)** — every page here assumes you have one.
