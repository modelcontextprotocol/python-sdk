---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

Eine **Middleware** ist eine einzelne async-Funktion, die jede Nachricht umschließt, die dein Server empfängt.

Du schreibst sie als `async (ctx, call_next)` und hängst sie an `server.middleware` an. Das ist die ganze API.

!!! warning
    Die Middleware-Liste ist im Quellcode als **provisorisch** markiert: Signatur und Semantik können
    sich in einem 2.x-Minor-Release ändern. Nutze sie zum *Beobachten* (Timing, Logging, Tracing) und
    zum *Ablehnen* von Nachrichten; mache sie nicht zum Fundament, auf dem dein Server steht.

`MCPServer` nimmt die Liste bei der Konstruktion entgegen (`MCPServer(name, middleware=[...])`) und stellt
sie als `mcp.middleware` bereit; der Low-Level-`Server` stellt dieselbe Liste als `server.middleware`
bereit. Das Beispiel unten verwendet den Low-Level-`Server`; wenn `Server(name, on_call_tool=...)` neu
für dich ist, lies zuerst **[Der Low-Level-Server](low-level-server.md)**.

## Eine Timing-Middleware {#a-timing-middleware}

Ein Server, ein Tool, eine Middleware, die loggt, wie lange jede Nachricht gedauert hat:

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` ist derselbe `ServerRequestContext`, den deine Handler erhalten. `ctx.method` ist der rohe
  Methoden-String; `ctx.params` sind die rohen Params, **vor** jeder Validierung.
* `call_next(ctx)` führt den Rest der Kette aus: Validierung, die Handler-Suche, deinen Handler.
  Gib zurück, was es zurückgegeben hat, und die Response bleibt unverändert.
* Das `try`/`finally` ist Absicht: Ein Handler, der eine Exception auslöst, wird trotzdem gemessen,
  denn der Fehlschlag erreicht deine Middleware als Exception aus `call_next`.
* `server.middleware.append(...)` registriert sie. Die Liste läuft von außen nach innen, also ist
  `middleware[0]` diejenige, die am nächsten an der Leitung sitzt.

### Ausprobieren {#try-it}

Verbinde einen Client, liste die Tools auf, rufe eines auf. Dein Log hat **drei** Zeilen:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

Du hast zwei Aufrufe gemacht und drei Zeilen bekommen. Die erste ist `server/discover`: der Request,
den der Client zum Aufbau der Verbindung geschickt hat, bevor du irgendetwas angefordert hast.

Genau darum geht es. Middleware umschließt **jede** eingehende Nachricht:

* Den Verbindungsaufbau: `server/discover`, oder `initialize` und `notifications/initialized`
  in einer Legacy-Session.
* Jeden Request und jede Benachrichtigung. Bei einer Benachrichtigung gilt `ctx.request_id is None`,
  `call_next(ctx)` gibt `None` zurück, und was immer du zurückgibst, wird verworfen.
* Sogar eine Methode, für die der Server keinen Handler hat: `call_next` wirft den
  `MCPError(-32601, "Method not found")` *durch* deine Middleware hindurch auf dem Weg zum Client.

## Was du in einer Middleware tun kannst {#what-you-can-do-inside-one}

In aufsteigender Reihenfolge danach, wie sehr du zögern solltest:

* **Beobachten.** Miss es, zähle es, logge es. Das Beispiel oben.
* **Ablehnen.** Wirf einen `MCPError` *statt* `call_next(ctx)` aufzurufen, und diese eine Nachricht
  wird mit einem JSON-RPC-Fehler beantwortet. Die Verbindung bleibt bestehen; die nächste Nachricht
  geht durch. So beschränkt ein Server `subscriptions/listen` pro Aufrufer:
  **[Entscheiden, wer zusehen darf](../handlers/subscriptions.md#deciding-who-may-watch)** auf der
  Seite Abonnements führt es Schritt für Schritt vor.
* **Umschreiben.** `ctx` ist eine Dataclass: `await call_next(dataclasses.replace(ctx, params=...))`
  reicht dem Rest der Kette andere Params weiter, als der Client geschickt hat. Tu das nie mit
  `initialize`: Das Ergebnis, das der Client zurückbekommt, wird aus deinen umgeschriebenen Params
  gebaut, aber der Server legt seinen Verbindungszustand anhand der ursprünglichen Params von der
  Leitung fest. Beide Seiten können den Handshake beenden und sich dabei uneinig sein, was sie
  ausgehandelt haben.
* **Antworten.** Gib ein Ergebnis zurück, ohne `call_next(ctx)` aufzurufen, und es geht als deine
  Response an den Client. `call_next` reicht dir die fertige Form für die Leitung, und die Pipeline
  bessert nie nach, was du zurückgibst – der ganze Umschlag gehört also dir: Auf einer Verbindung der
  2026er-Generation gehört dazu der `serverInfo`-Stempel in `_meta`, den das SDK an Handler-Ergebnisse
  anfügt, an deine aber nicht.

!!! check
    `initialize` gehört zu dem, was Middleware umschließt, und es ist der *einzige* Hook, den du
    dafür bekommst. Versuchst du, es mit `add_request_handler` zu übernehmen, weigert sich das SDK:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` wird inline behandelt: Der Server liest keine weiteren eingehenden Nachrichten, bis
    deine Middleware-Kette zurückkehrt. Auf einen Server-zu-Client-Request zu warten
    (`ctx.session.send_request(...)`, eine Elicitation – Rückfrage bei der Person am Host), während
    `initialize` behandelt wird, **blockiert die Verbindung** daher **dauerhaft** (Deadlock): Die
    Response, auf die du wartest, kann nie gelesen werden. Benachrichtigungen nach dem
    Fire-and-forget-Prinzip sind in Ordnung.

## Die eine Middleware, die standardmäßig aktiv ist {#the-one-middleware-that-ships-on-by-default}

Das SDK liefert genau eine Middleware mit, und sie steht bereits auf der Liste deines Servers: die,
die für jede Nachricht einen OpenTelemetry-Span ausgibt. Du hängst sie nicht an, und meistens denkst
du gar nicht an sie. Sie tut nichts, bis du einen Exporter installierst, und sie hat ihre eigene Seite:
**[OpenTelemetry](../run/opentelemetry.md)**.

!!! info
    Wenn du schon ASGI-Middleware geschrieben hast, kennst du diese Form bereits. Aus Starlettes
    `(scope, receive, send)` wurde `(ctx, call_next)`, und sie läuft *nach* dem Transport, auf der
    dekodierten Nachricht statt auf dem rohen HTTP-Request. Beide lassen sich kombinieren:
    Starlette-Middleware auf `streamable_http_app()` sieht HTTP; diese hier sieht MCP.

## Zusammenfassung {#recap}

* Eine Middleware ist `async (ctx, call_next) -> result`, übergeben als `MCPServer(middleware=[...])`
  (oder an `mcp.middleware` angehängt) und beim Low-Level-`Server` an `server.middleware` angehängt.
* Sie umschließt **jede** eingehende Nachricht (`server/discover`, `initialize`, Requests,
  Benachrichtigungen, unbekannte Methoden) und läuft von außen nach innen.
* An `ctx.request_id is None` unterscheidest du eine Benachrichtigung von einem Request.
* Wirf eine Exception, statt `call_next` aufzurufen, um eine einzelne Nachricht abzulehnen; die
  Verbindung überlebt.
* Das OpenTelemetry-Tracing des SDK ist ebenfalls eine Middleware und steht schon auf der Liste. Siehe
  **[OpenTelemetry](../run/opentelemetry.md)**.
* Die ganze Oberfläche ist provisorisch. Beobachte damit; baue nicht darauf.

Das ist alles, was einen Request umschließt. **[Autorisierung](../run/authorization.md)** entscheidet,
ob der Request überhaupt laufen darf.
