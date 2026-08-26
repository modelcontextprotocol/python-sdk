---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# Veraltete Features {#deprecated-features}

Die Spec 2026-07-28 mustert fünf Dinge aus. Das SDK implementiert jedes davon weiterhin, und jedes davon trägt jetzt eine **Deprecation-Warnung**. Ein SDK-Helfer ist unabhängig davon veraltet und steht [am Ende](#deprecated-sdk-helpers).

Die Tabelle unten nennt jedes veraltete Feature, den Grund, warum es verschwindet, und den Ersatz, auf dem du aufbauen solltest.

## Was veraltet ist {#what-is-deprecated}

| Veraltet | Warum | Was du stattdessen tust |
|---|---|---|
| **Roots**: `ctx.session.list_roots()`, `client.send_roots_list_changed()`, der `list_roots_callback=`, den du an `Client(...)` übergibst | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) mustert die Capability aus. | Nimm die Pfade als gewöhnliche Tool-Argumente oder Ressourcen-URIs entgegen, oder bette einen `ListRootsRequest` in ein `InputRequiredResult` ein (siehe **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)**). |
| **Serverseitig initiiertes Sampling**: `ctx.session.create_message()`, der `sampling_callback=`, den du an `Client(...)` übergibst | SEP-2577 mustert die Capability aus. | Gib `InputRequiredResult` zurück und lass den Client den Aufruf wiederholen (siehe **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)**). |
| **Protokoll-Logging**: `ctx.log()`, `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`, `ctx.session.send_log_message()`, `client.set_logging_level()` | SEP-2577 mustert die Capability aus. Innerhalb des Protokolls ersetzt sie nichts. | Gewöhnliches `import logging` nach stderr (siehe **[Logging](handlers/logging.md)**). |
| **`ping`**: `client.send_ping()` | Aus dem Protokoll **entfernt**, nicht bloß veraltet. In 2026-07-28 gibt es keine Methode `ping`. | Nichts. Es funktioniert nur gegen eine `mode="legacy"`-Verbindung. |
| **Progress vom Client zum Server**: `client.send_progress_notification()` | 2026-07-28 erlaubt Progress nur noch vom Server zum Client. | Es gibt nichts zu senden. Dein *Server* meldet Fortschritt mit `ctx.report_progress()` (siehe **[Progress](handlers/progress.md)**). |

Drei Dinge ergeben sich aus dieser Tabelle:

* Roots, Sampling und Logging gehören zusammen. Ein einziger Vorschlag, **SEP-2577**, erklärt alle drei Capabilities auf einmal für veraltet.
* Sampling und Roots teilen ein tieferes Problem: Es sind Stellen, an denen ein **Server** einen **Request** an den **Client** sendet. Genau diese Richtung ersetzt 2026-07-28 durch **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)** (multi-round-trip requests). Verschwunden sind die eigenständigen RPC-Methoden (`sampling/createMessage`, `roots/list` und das Push-artige `elicitation/create`); die Payload-Typen `CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` bleiben erhalten, eingebettet in `InputRequiredResult.input_requests`, und auf dem Client landen sie bei denselben Callbacks.
* `ping` fällt aus der Reihe. Das Protokoll erklärt es nicht für veraltet, es entfernt es. Die SDK-Methode warnt trotzdem (ihre Meldung sagt *removed*, nicht *deprecated*), und ein Aufruf auf einer modernen Verbindung wird mit *„Method not found“* beantwortet.

## Veraltet ist ein Hinweis, kein Verbot {#deprecated-is-advisory}

Heute geht nichts kaputt.

Jede der oben genannten Methoden funktioniert weiterhin gegen jede Session, die **2025-11-25 oder früher** ausgehandelt hat. Pinne `mode="legacy"` auf dem Client, und du bekommst exakt das Verhalten von vor 2026. Auf der Leitung ändert sich nichts, und das Aushandeln der Capabilities bleibt unverändert.

Was sich ändert: Du bekommst eine sichtbare Warnung, wenn eine davon zum ersten Mal läuft:

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` ist eine Unterklasse von `UserWarning`, **nicht** von `DeprecationWarning`. Das ist Absicht: Pythons Standardfilter zeigt `DeprecationWarning` nur in Code, der direkt als `__main__` läuft – so erklären Bibliotheken Dinge für veraltet, und zwei Jahre lang merkt es niemand. Diese hier erscheint überall, ganz ohne `-W`-Flag.

!!! warning
    Der Hinweischarakter endet an der Leitung. Sampling und Roots sind *Requests* vom Server
    an den Client, und eine 2026-07-28-Session hat keinen Kanal, der einen solchen transportiert.
    Rufst du `ctx.session.create_message()` in einem Tool auf einer modernen Verbindung auf,
    wird die Warnung trotzdem ausgelöst, und danach schlägt das Senden mit einem Fehler fehl:

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    Zwei Signale, in dieser Reihenfolge. Die `MCPDeprecationWarning` wird in dem Moment
    ausgelöst, in dem du die Methode aufrufst, auf jeder Verbindung. Der Fehler ist das, was
    zurückkommt, wenn das SDK anschließend zu senden versucht. Beide funktionieren nur auf einer
    `mode="legacy"`-Verbindung von Anfang bis Ende, deren Client den passenden Callback
    registriert hat.

## `ping` auf einer Legacy-Session {#ping-on-a-legacy-session}

Ein **Ping** ist ein leerer Request, den jede Seite senden kann, um zu prüfen, ob die andere noch antwortet. Die Spec 2026-07-28 entfernt ihn ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)): Jeder Request, den ein moderner Client sendet, beweist bereits, dass der Server da ist, und ein moderner Server hat keinen Kanal, um selbst einen zu senden. Beide SDK-Methoden funktionieren weiterhin auf einer Session der Handshake-Generation. Vom Client aus:

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

Und vom Server aus, in jedem beliebigen Handler:

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` warnt bei jedem Aufruf mit `MCPDeprecationWarning`. Auf einer Standardverbindung (`2026-07-28`) antwortet der Server stattdessen mit `MCPError: Method not found`.
* `ctx.session.send_ping()` trägt keine Warnung. Auf einer modernen Verbindung löst es denselben Fehler wegen des fehlenden Rückkanals (back-channel) aus wie jeder andere serverseitig initiierte Request.
* Keine der beiden Seiten registriert etwas, um einen Ping zu beantworten.

## Änderungsbenachrichtigungen für Roots {#roots-change-notifications}

Ein Client der 2025er-Generation, der die Roots-Capability deklariert hat, kann dem Server mitteilen, dass sich seine Arbeitsordner geändert haben, indem er `notifications/roots/list_changed` sendet; der Server reagiert, indem er `roots/list` erneut anfordert. Die Spec 2026-07-28 entfernt die Benachrichtigung zusammen mit dem restlichen Push-artigen Roots-Ablauf. Auf dem Client ist es das Übergeben von `list_roots_callback=` (**[Client-Callbacks](client/callbacks.md)**), das `"roots": {"listChanged": true}` deklariert, und ein einziger Aufruf hält dieses Versprechen:

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

Auf dem Server nimmt der Low-Level-`Server` den empfangenden Handler entgegen:

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` ist die Liste, die dein `list_roots_callback` zurückgibt. `client.send_roots_list_changed()` warnt, und es braucht einen `mode="legacy"`-Client: Auf einer modernen Verbindung wird die Benachrichtigung stillschweigend verworfen. Halte die Session danach offen, denn der nachfolgende `roots/list`-Request des Servers kommt darüber an.
* `MCPServer` hat keinen Hook für die Benachrichtigung. Auf dem Low-Level-`Server` registriert `on_roots_list_changed=` den Handler (ebenfalls veraltet, und er warnt beim Konstruieren). Die Benachrichtigung trägt keine Payload, also ruft der Handler `ctx.session.list_roots()` auf, um die neue Liste zu holen.

## Die Warnung unterdrücken {#silencing-the-warning}

Tu es nicht, in neuem Code.

Ein Server, den du pflegst und der tatsächlich Clients von vor 2026 bedient, hat aber jedes Recht auf ein ruhiges Log. Filtere die Kategorie, bevor der erste veraltete Aufruf läuft:

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

Das ist die ganze API. Es gibt keinen Schalter pro Methode, und du willst auch keinen: Der Sinn einer einzigen Kategorie ist, dass eine Zeile sie zum Schweigen bringt und eine Zeile sie zurückholt.

!!! check
    Dreh den Filter um, und du bekommst einen Regressionstest geschenkt. Füge
    `"error::mcp.MCPDeprecationWarning"` zur Einstellung `filterwarnings` in deiner
    pytest-Konfiguration hinzu, und der veraltete Aufruf **wirft eine Exception**, statt zu
    warnen. Ein Tool namens `old_log`, das noch `ctx.info()` aufruft, besteht nicht mehr: Der
    Aufruf kommt mit `is_error=True` und `Error executing tool old_log` zurück, und das
    mitgeschnittene Server-Log nennt den Schuldigen:

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    Eine Zeile pytest-Konfiguration, und ein veralteter Aufruf kann sich nie wieder in deine
    Codebasis schleichen, ohne einen Test fehlschlagen zu lassen.

## Veraltete SDK-Helfer {#deprecated-sdk-helpers}

Das sind keine Spec-Änderungen, sondern nur SDK-Interna mit einem besseren Ersatz. Sie warnen mit derselben `MCPDeprecationWarning` und werden in 3.0 entfernt.

| Veraltet | Was du stattdessen tust |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | `FuncMetadata.validate_arguments()` und danach `FuncMetadata.call_fn()`. Aufgerufen hat es ohnehin nur Code, der `FuncMetadata` direkt ansteuert (etwa eine eigene `Tool`-Unterklasse). |

## Zusammenfassung {#recap}

* Die Spec 2026-07-28 erklärt **Roots**, serverseitig initiiertes **Sampling** und Protokoll-**Logging** für veraltet (alle [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)), beschränkt **Progress** auf die Richtung vom Server zum Client und entfernt **`ping`**.
* Die Ersatzspalte weist dir den Weg: **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)** für Sampling und Roots, **[Logging](handlers/logging.md)** für Logging, **[Progress](handlers/progress.md)** für Progress. `ping` braucht gar nichts.
* Veraltet ist ein Hinweis: keine Änderungen auf der Leitung, alles funktioniert weiterhin gegen Sessions von vor 2026, und du bekommst eine sichtbare `MCPDeprecationWarning` (eine `UserWarning`, also standardmäßig aktiv).
* Sampling und Roots brauchen zusätzlich einen Rückkanal, den eine 2026-07-28-Session nicht hat. Auf einer modernen Verbindung warnen sie und werfen dann eine Exception.
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` bringt die ganze Kategorie zum Schweigen; `"error::mcp.MCPDeprecationWarning"` in pytest macht daraus einen fehlschlagenden Test.
* Ein SDK-Helfer, `FuncMetadata.call_fn_with_arg_validation()`, ist separat veraltet und wird in 3.0 entfernt.
* Neuer Code sollte auf nichts davon aufbauen.

Jede andere Seite dieser Dokumentation vermittelt die aktuelle API.
