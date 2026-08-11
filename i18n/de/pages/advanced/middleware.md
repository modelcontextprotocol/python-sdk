---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

Eine **Middleware** ist eine einzelne async-Funktion, die jede Nachricht umschließt, die dein Server empfängt.

Du schreibst sie als `async (ctx, call_next)` und hängst sie an `server.middleware` an. Das ist die ganze API.

!!! warning
    Die Middleware-Liste ist im Quellcode als **provisional** markiert: Signatur und Semantik können
    sich in einem 2.x-Minor-Release ändern. Nutze sie zum *Beobachten* (Timing, Logging, Tracing) und zum
    *Ablehnen* von Nachrichten; mach sie nicht zum Fundament, auf dem dein Server steht.

`MCPServer` nimmt die Liste beim Erzeugen entgegen (`MCPServer(name, middleware=[...])`) und stellt sie als
`mcp.middleware` bereit; der Low-Level-`Server` stellt dieselbe Liste als `server.middleware` bereit. Das Beispiel
unten verwendet den Low-Level-`Server`; wenn `Server(name, on_call_tool=...)` neu für dich ist, lies zuerst
**[Der Low-Level-Server](low-level-server.md)**.

## Eine Timing-Middleware {#a-timing-middleware}

Ein Server, ein Tool, eine Middleware, die loggt, wie lange jede Nachricht gebraucht hat:

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` ist derselbe `ServerRequestContext`, den deine Handler erhalten. `ctx.method` ist der rohe
  Methoden-String; `ctx.params` sind die rohen Parameter, **vor** jeder Validierung.
* `call_next(ctx)` führt den Rest der Kette aus: Validierung, die Suche nach dem Handler, deinen Handler.
  Gib zurück, was es zurückgegeben hat, und die Response bleibt unverändert.
* Das `try`/`finally` ist Absicht: Auch ein Handler, der eine Exception auslöst, wird gemessen, denn der
  Fehler erreicht deine Middleware als Exception aus `call_next`.
* `server.middleware.append(...)` registriert sie. Die Liste läuft von außen nach innen, also ist
  `middleware[0]` die Middleware, die der Leitung am nächsten ist.

### Ausprobieren {#try-it}

Verbinde einen Client, liste die Tools auf, rufe eines auf. Dein Log hat **drei** Zeilen:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

Du hast zwei Aufrufe gemacht und drei Zeilen bekommen. Die erste ist `server/discover`: der Request, den der
Client geschickt hat, um die Verbindung aufzubauen, bevor du irgendetwas angefordert hast.

Genau darum geht es. Middleware umschließt **jede** eingehende Nachricht:

* Den Verbindungsaufbau: `server/discover`, oder `initialize` und `notifications/initialized`
  auf einer Legacy-Session.
* Jeden Request und jede Benachrichtigung. Bei einer Benachrichtigung gilt `ctx.request_id is None`,
  `call_next(ctx)` gibt `None` zurück, und was immer du zurückgibst, wird verworfen.
* Sogar eine Methode, für die der Server keinen Handler hat: `call_next` wirft den
  `MCPError(-32601, "Method not found")` *durch* deine Middleware hindurch auf dem Weg zum Client.

## Was innerhalb einer Middleware möglich ist {#what-you-can-do-inside-one}

In aufsteigender Reihenfolge danach, wie sehr du zögern solltest:

* **Beobachten.** Messen, zählen, loggen. Das Beispiel oben.
* **Ablehnen.** Löse einen `MCPError` aus, *statt* `call_next(ctx)` aufzurufen, und diese eine Nachricht wird
  mit einem JSON-RPC-Fehler beantwortet. Die Verbindung bleibt bestehen; die nächste Nachricht geht durch. So
  schränkt ein Server `subscriptions/listen` pro Aufrufer ein:
  **[Entscheiden, wer zusehen darf](../handlers/subscriptions.md#deciding-who-may-watch)** auf der Seite
  Abonnements geht das Schritt für Schritt durch.
* **Umschreiben.** `ctx` ist eine Dataclass: `await call_next(dataclasses.replace(ctx, params=...))`
  reicht dem Rest der Kette andere Parameter weiter, als der Client geschickt hat. Tu das niemals bei
  `initialize`: Das Ergebnis, das der Client zurückbekommt, wird aus deinen umgeschriebenen Parametern gebaut,
  aber der Server legt seinen Verbindungszustand anhand der ursprünglichen Parameter von der Leitung fest. Beide
  Seiten können den Handshake abschließen und sich dabei uneinig sein, was sie ausgehandelt haben.
* **Beantworten.** Gib ein Ergebnis zurück, ohne `call_next(ctx)` aufzurufen, und es geht als deine Response
  an den Client. `call_next` reicht dir die fertige Form für die Leitung, und die Pipeline bessert nie nach,
  was du zurückgibst – der ganze Umschlag gehört also dir: Auf einer Verbindung der 2026er-Generation schließt
  das den `_meta`-Stempel `serverInfo` ein, den das SDK an Handler-Ergebnisse anhängt, an deine aber nicht.

!!! check
    `initialize` gehört zu den Dingen, die Middleware umschließt, und es ist der *einzige* Hook, den du
    dafür bekommst. Versuchst du, es mit `add_request_handler` zu übernehmen, lehnt das SDK ab:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` wird inline verarbeitet: Der Server liest keine weiteren eingehenden Nachrichten, bis deine
    Middleware-Kette zurückkehrt. Auf einen Request vom Server an den Client zu warten (`ctx.session.send_request(...)`,
    eine Elicitation (Rückfrage bei der Person am Host)), während `initialize` verarbeitet wird, führt daher zu
    einem **Deadlock der Verbindung**: Die Response, auf die du wartest, kann nie gelesen werden.
    Fire-and-forget-Benachrichtigungen sind in Ordnung.

## Die eine Middleware, die standardmäßig aktiv ist {#the-one-middleware-that-ships-on-by-default}

Das SDK liefert genau eine Middleware mit, und sie steht bereits auf der Liste deines Servers: die, die für
jede Nachricht einen OpenTelemetry-Span erzeugt. Du hängst sie nicht an, und meistens denkst du gar nicht
an sie. Sie tut nichts, bis du einen Exporter installierst, und sie hat ihre eigene Seite:
**[OpenTelemetry](../run/opentelemetry.md)**.

!!! info
    Wenn du schon ASGI-Middleware geschrieben hast, kennst du diese Form bereits. Starlettes
    `(scope, receive, send)` wurde zu `(ctx, call_next)`, und es läuft *nach* dem Transport, auf
    der dekodierten Nachricht statt auf dem rohen HTTP-Request. Beides lässt sich kombinieren: Starlette-Middleware
    auf `streamable_http_app()` sieht HTTP; diese hier sieht MCP.

## Zusammenfassung {#recap}

* Eine Middleware ist `async (ctx, call_next) -> result`, übergeben als `MCPServer(middleware=[...])` (oder
  an `mcp.middleware` angehängt) und beim Low-Level-`Server` an `server.middleware` angehängt.
* Sie umschließt **jede** eingehende Nachricht (`server/discover`, `initialize`, Requests, Benachrichtigungen,
  unbekannte Methoden) und läuft von außen nach innen.
* An `ctx.request_id is None` unterscheidest du eine Benachrichtigung von einem Request.
* Löse eine Exception aus, statt `call_next` aufzurufen, um eine einzelne Nachricht abzulehnen; die Verbindung überlebt.
* Das eigene OpenTelemetry-Tracing des SDK ist ebenfalls eine Middleware, die schon auf der Liste steht. Siehe
  **[OpenTelemetry](../run/opentelemetry.md)**.
* Die gesamte Oberfläche ist provisorisch. Beobachte damit; baue nicht darauf.

Das ist alles, was einen Request umschließt. **[Autorisierung](../run/authorization.md)** entscheidet, ob der Request
überhaupt laufen darf.
