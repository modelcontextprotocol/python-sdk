# Events

[SEP-3415](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3415) lets a server
tell clients that something happened: a new incident, an email, a merged PR. A client subscribes
to an **event type** with arguments, such as `incident.created` for the `billing` service. It
then receives each matching **event** by polling or at a webhook.

The SDK ships this as the `Events` extension (`io.modelcontextprotocol/events`), with a server
side and a client side. If [Extensions](extensions.md) are new to you, skim that page first.

!!! warning "Experimental: the wire format may change"
    SEP-3415 is a draft. Events lives under `mcp.experimental.events`, and its API and wire
    format may change in any release until the SEP is accepted. Push delivery (`events/stream`)
    is not implemented yet.

## Offering events

```python title="server.py"
from pydantic import BaseModel

from mcp.experimental.events.server import Events
from mcp.server.mcpserver import MCPServer


class IncidentFilter(BaseModel):
    service: str


class Incident(BaseModel):
    service: str
    title: str


events = Events()
incidents = events.event(
    "incident.created",
    arguments=IncidentFilter,
    payload=Incident,
    description="A new incident was opened",
)


@incidents.match
def same_service(arguments: IncidentFilter, incident: Incident) -> bool:
    return arguments.service == incident.service


mcp = MCPServer("pager", extensions=[events])


@mcp.tool()
def open_incident(service: str, title: str) -> str:
    """Open an incident."""
    incidents.emit(Incident(service=service, title=title))
    return "opened"
```

* `events.event(...)` declares an event type. `arguments` is the model subscribers pass, and
  `payload` is the model each event carries. `events/list` publishes both as JSON Schema, and
  arguments are validated before your code sees them.
* `emit` records an event. The server keeps the most recent events in a bounded buffer, so a
  client that polls every few seconds misses nothing.
* `match` decides which subscribers receive an emitted event. Without it, everyone does.
  Use `transform` the same way to reshape an event per subscriber, for example to redact fields.

Use `NoArguments` for an event type that takes no arguments.

### Reading from an upstream with a check function

When the upstream can answer "what happened since this cursor", register a check function
instead of calling `emit`:

```python title="server.py"
from datetime import timedelta

from pydantic import BaseModel

from mcp.experimental.events.server import EventBatch, EventQuery, Events, Occurrence
from mcp.server.mcpserver import MCPServer


class Repository(BaseModel):
    name: str


class Push(BaseModel):
    sha: str


events = Events()
pushes = events.event("repo.pushed", arguments=Repository, payload=Push)


@pushes.check
async def check(query: EventQuery[Repository]) -> EventBatch[Push]:
    commits, position = await upstream_commits(query.arguments.name, after=query.cursor)
    return EventBatch(
        cursor=position,
        events=[Occurrence(Push(sha=sha), id=sha) for sha in commits],
        next_poll=timedelta(seconds=30),
    )


async def upstream_commits(repository: str, after: str | None) -> tuple[list[str], str]:
    return [], "head"


mcp = MCPServer("git", extensions=[events])
```

The cursor is yours: an offset, a history id, a timestamp. A `None` cursor means "start from
now", so the SDK returns your cursor with no events. Set the occurrence `id` to the upstream's
own identifier, because clients deduplicate on it.

Return `truncated=True` when the events start later than the cursor, for example because it
fell out of the upstream's retention window. Clients use it to know they missed something.

### Subscription hooks

```python title="server.py"
from pydantic import BaseModel

from mcp.experimental.events.server import Events, Subscriber
from mcp.server.mcpserver import MCPServer


class IncidentFilter(BaseModel):
    service: str


class Incident(BaseModel):
    service: str
    title: str


events = Events()
incidents = events.event("incident.created", arguments=IncidentFilter, payload=Incident)
watched: dict[str, int] = {}


@incidents.on_subscribe
async def start_watching(subscriber: Subscriber[IncidentFilter]) -> None:
    service = subscriber.arguments.service
    watched[service] = watched.get(service, 0) + 1


@incidents.on_unsubscribe
async def stop_watching(subscriber: Subscriber[IncidentFilter]) -> None:
    watched[subscriber.arguments.service] -= 1


mcp = MCPServer("pager", extensions=[events])
```

Hooks let you set up and tear down upstream work per subscription. A poll client never says
goodbye, so the SDK leases poll subscriptions: `on_subscribe` runs on the first poll for a
principal, event type, and arguments, and `on_unsubscribe` runs once no poll renewed the lease
for `poll_lease` (three poll intervals by default).

## Webhook delivery

```python
from mcp.experimental.events.server import Events, Webhooks

events = Events(webhooks=Webhooks())
```

Passing `Webhooks` offers webhook delivery for every event type. The client gives a callback URL
and a secret, and the server POSTs each event there, signed with
[Standard Webhooks](https://www.standardwebhooks.com/). It retries failed deliveries, and reports
failures to the client when it refreshes the subscription.

!!! warning "Webhooks need an authenticated principal"
    A subscription is identified by who made it, the callback URL, the event type, and the
    arguments. Without a principal anyone could cancel or hijack another caller's subscription,
    so the server refuses webhook calls with `Forbidden` unless the caller is authenticated.
    By default the principal comes from the request's OAuth access token. Pass
    `Events(principal=...)` to derive it another way.

Callback URLs come from clients, so the server treats them as hostile:

* Only `https` URLs are accepted.
* The host is resolved before every request, and refused unless every address is public.
  The server connects to the address it checked, so a DNS answer cannot change in between.
* Redirects are never followed.
* Before the first delivery, the endpoint must echo a random challenge, so a server cannot be
  used to POST at a URL that never asked for events.

For a receiver on your machine during development, allow its origin explicitly:

```python
from mcp.experimental.events.server import Events, Webhooks

events = Events(webhooks=Webhooks(trusted_origins=["http://127.0.0.1:9000"]))
```

Subscriptions live in memory. The server caps each one at `max_ttl` (one hour by default), and
clients refresh before it lapses. After a restart, clients subscribe again.

## Consuming events

### Polling

```python title="client.py"
import anyio

from mcp.client import Client
from mcp.experimental.events.client import Events


async def main() -> None:
    async with Client("http://localhost:8000/mcp", extensions=[Events()]) as client:
        events = client.extension(Events)
        async for batch in events.watch("incident.created", {"service": "billing"}):
            for event in batch.events:
                print(event.event_id, event.data)


anyio.run(main)
```

`watch` polls in a loop. It waits as long as the server asks (`nextPollMs`), never less than
`Events(min_poll_interval=...)`, and polls again at once while the server has more. It yields
only batches that have events or report a gap (`batch.truncated`).

To resume after a restart, save `batch.cursor` once you handled a batch, and pass it back with
`watch(..., cursor=saved)`. Delivery is at least once, so deduplicate on `event_id`.

For a single read, use `events.poll(...)`.

### Webhooks

```python title="client.py"
import base64
import secrets

import anyio
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from mcp.client import Client
from mcp.experimental.events.client import Events
from mcp.experimental.events.receiver import Delivery, WebhookReceiver

SECRET = "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode()


async def handle(delivery: Delivery) -> None:
    print(delivery)


receiver = WebhookReceiver(SECRET, handle)
app = Starlette(routes=[Mount("/hooks/events", receiver)])


async def main() -> None:
    config = uvicorn.Config(app, port=9000)
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(uvicorn.Server(config).serve)
        async with Client("https://pager.example.com/mcp", extensions=[Events()]) as client:
            events = client.extension(Events)
            async with events.subscribe(
                "incident.created",
                {"service": "billing"},
                url="https://hooks.example.com/hooks/events",
                secret=SECRET,
            ):
                await anyio.sleep_forever()


anyio.run(main)
```

`subscribe` holds the subscription for the duration of the block. It refreshes it before it
expires, and unsubscribes on exit.

`WebhookReceiver` is an ASGI app for the callback URL. It answers the verification challenge,
rejects requests that are unsigned, signed with another secret, or more than five minutes old,
and passes each delivery to your handler:

| Delivery | Meaning |
| --- | --- |
| `EventOccurrence` | An event. `cursor` is the subscription's position after it. |
| `WebhookGap` | Events were skipped. Reconcile if you need every event. |
| `WebhookTerminated` | The server ended the subscription, for example because access was revoked. |

The receiver drops repeated `event_id`s, since servers retry. A secret is `whsec_` followed by
the base64 of 24 to 64 random bytes, as `SECRET` shows. Store it, since the receiver needs the
same secret after a restart.
