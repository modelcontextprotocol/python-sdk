---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# Der Low-Level-Server {#the-low-level-server}

`@mcp.tool()` ist eine Schicht. Darunter liegt eine zweite Server-Klasse, `Server`, die rohes MCP spricht: Du gibst ihr die Protokollobjekte, und sie legt sie unverändert auf die Leitung.

`MCPServer` ist darauf aufgebaut. Du steigst hinab, wenn die Komfortschicht im Weg ist:

* Du musst ein **exaktes** Schema ausgeben (aus einer Datei geladen, aus einer Datenbank generiert), nicht eines, das aus einer Python-Signatur abgeleitet ist.
* Du brauchst die volle Kontrolle über das Ergebnis: `_meta`, `is_error`, jeden Schlüssel von `structured_content`.
* Du musst eine Methode behandeln, die MCP nicht definiert.

Für alles andere bleib bei `MCPServer`.

## Dasselbe Tool, von Hand {#the-same-tool-by-hand}

Das ist das Tool `search_books`, das **[Tools](../servers/tools.md)** in neun Zeilen `@mcp.tool()` schreibt, ohne den Zucker:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

Drei Dinge haben sich geändert, und sie sind die ganze Low-Level-API:

* **Handler sind Konstruktorparameter.** `on_list_tools=` und `on_call_tool=` wandern in `Server(...)`. Hier unten gibt es keine Dekoratoren, und jeder Handler hat dieselbe Form: `async (ctx, params) -> result`.
* **Du schreibst das Input-Schema.** `Tool.input_schema` ist ein schlichtes JSON-Schema-`dict`. Niemand leitet es aus Type Hints ab, denn es gibt keine Type Hints, aus denen man es ableiten könnte.
* **Du baust das Ergebnis.** `CallToolResult(content=[TextContent(...)])`, von Hand. Nichts wird verpackt, konvertiert oder aus einer Rückgabeannotation abgeleitet.

`params` ist der geparste Request: `CallToolRequestParams` gibt dir `.name` und `.arguments`. `ctx` ist ein `ServerRequestContext`: `ctx.session` zum Zurücksprechen an den Client, `ctx.lifespan_context`, `ctx.request_id` und `ctx.meta`, das eingehende `_meta` des Requests.

!!! info
    Wenn du FastAPI kennst, kennst du diese Beziehung bereits. `MCPServer` ist die Schicht aus Dekoratoren und Type Hints; `Server` ist das Starlette darunter. Sie sind keine Rivalen: `MCPServer` erzeugt einen `Server` und registriert darauf genau solche Handler wie diese.

### Ausprobieren {#try-it}

Hierfür gibt es keinen Inspector: `mcp dev` und `mcp run` akzeptieren nur einen `MCPServer`. Dem In-Memory-`Client` ist das egal; er nimmt einen Low-Level-`Server` genauso wie einen `MCPServer`:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

Derselbe Text, den die `@mcp.tool()`-Version erzeugt hat. Zwei ehrliche Unterschiede:

* `result.structured_content` ist `None`. Der High-Level-Server verpackt ein `-> str` für dich in `{"result": ...}`; hier baut niemand, was du nicht gebaut hast.
* `list_tools` gibt das Schema zurück, das **du** getippt hast, Zeichen für Zeichen. Die High-Level-Version hatte `"title": "Query"` auf jeder Property und ein `"title": "search_booksArguments"` an der Wurzel: Pydantic-Artefakte. Hier unten gilt: Was auf der Leitung ist, hast du dort hingelegt.

## Nichts wird für dich geprüft {#nothing-is-checked-for-you}

`MCPServer` weist ein fehlerhaftes Argument ab, bevor deine Funktion überhaupt läuft, indem er den Aufruf gegen das generierte Schema validiert (**[Tools](../servers/tools.md)**).

`Server` tut das nicht. Dein `input_schema` wird dem Client *angekündigt*; es wird nie auf `params.arguments` *angewendet*.

!!! check
    Ruf `search_books` ohne `limit` auf, und dein `args["limit"]` löst einen `KeyError` aus. Der Client sieht:

    ```text
    MCPError: Internal server error
    ```

    Ein JSON-RPC-Fehler, Code `-32603`, mit einer bewusst generischen Meldung: Das SDK gibt deinen Traceback nicht an einen entfernten Aufrufer preis. Das Modell erfährt nie, was es falsch gemacht hat, kann es also nicht erneut versuchen. (In einem Test bringt `raise_exceptions=True` stattdessen die echte Exception zum Vorschein; siehe **[Testen](../get-started/testing.md)**.)

Das lässt sich verallgemeinern. Eine Exception, die ein Low-Level-Handler auslöst, ist **immer** ein Protokollfehler, nie ein Tool-Ergebnis mit `is_error=True`. Wenn das Modell den Fehlschlag lesen und sich erholen soll, validiere `params.arguments` selbst und gib `CallToolResult(content=[TextContent(...)], is_error=True)` zurück. Die beiden Arten von Fehlschlägen sind das Thema von **[Fehler behandeln](../servers/handling-errors.md)**.

## Zwei Tools, ein Handler {#two-tools-one-handler}

`on_call_tool` ist der einzige Einstiegspunkt für jedes Tool auf dem Server. Du verzweigst über `params.name`:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` kündigt beide an. `call_tool` verteilt nach dem Namen.
* Der `else`-Zweig ist wichtig: `Server` leitet ein `tools/call` für einen Namen, den du nie gelistet hast, bereitwillig direkt in deinen Handler weiter. Löst du dort eine Exception aus, wird aus dem Aufruf dasselbe `-32603` wie oben.

## Strukturierte Ausgabe, von Hand {#structured-output-by-hand}

Deklariere `output_schema` auf dem `Tool` und setze `structured_content` auf das Ergebnis. Beides liegt bei dir:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

Ruf es auf, und das Ergebnis trägt beide Darstellungen:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

Der `_meta`-Block ist der Identitätsstempel des Servers: Das SDK fügt ihn jedem Ergebnis der 2026er-Generation hinzu, mit der `version` aus dem Konstruktor (ein Server, der keine setzt, meldet einen leeren String). Ein Server, der sich nicht zu erkennen geben darf, kann den Schlüssel mit einer Middleware entfernen, der die Ergebnisse gehören, die sie zurückgibt.

Der Server vergleicht die beiden Felder nie. Der `Client` dieses SDK schon: Gibst du `structured_content` zurück, das das von dir deklarierte `output_schema` nicht erfüllt, löst `call_tool` einen `RuntimeError` aus, der mit `Invalid structured content returned by tool search_books` beginnt und dann den `jsonschema`-Fehler zitiert. Ein Schema zu versprechen ist billig; es einzuhalten liegt bei dir. Die ganze Stufenleiter der Rückgabetypen und Schemas steht in **[Strukturierte Ausgabe](../servers/structured-output.md)**.

## `_meta`: für die Anwendung, nicht für das Modell {#\_meta-for-the-application-not-the-model}

`content` ist der Teil der Antwort, den das Modell liest. `structured_content` ist dieselbe Antwort als typisierte Daten. `_meta` ist der dritte Kanal: Daten, die mit dem Ergebnis für die **Client-Anwendung** mitreisen, ohne überhaupt Teil der Antwort zu sein.

Nutze es für Datensatz-IDs, Trace-IDs, alles, was deine UI braucht und dein Prompt nicht:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* Du erzeugst es als `_meta=`, dem Namen auf der Leitung. Der Client liest es als `result.meta` zurück.
* Versieh deine Schlüssel mit einem Namensraum (`bookshop/record_ids`). Die Schlüssel `io.modelcontextprotocol/*` sind vom Protokoll reserviert.

!!! warning
    `_meta` ist eine Konvention zwischen dir und der Client-Anwendung, keine Garantie darüber, was
    das Modell erreicht. Der Host entscheidet, was er darstellt. Lege niemals ein Geheimnis in irgendeinen Teil eines Tool-Ergebnisses.

## Capabilities folgen deinen Handlern {#capabilities-follow-your-handlers}

Ein `Server` kündigt genau die Methodenfamilien an, für die du ihm Handler gegeben hast. Der `Bookshop` oben übergibt `on_list_tools` und `on_call_tool` und sonst nichts, also sieht ein Client, der sich mit ihm verbindet:

```json
{"tools": {"listChanged": false}}
```

Kein `resources`, kein `prompts`: Es gibt nichts, was dahinter stünde. Übergib `on_list_prompts`, und `prompts` erscheint; übergib `on_completion`, und `completions` erscheint.

`MCPServer` kündigt Tools, Ressourcen und Prompts immer an, ob du welche registriert hast oder nicht, weil seine Manager immer existieren. Hier unten *ist* die Deklaration der Konstruktoraufruf.

## Der Lifespan-Generic {#the-lifespan-generic}

`Server` ist generisch im Typ, den sein Lifespan liefert. Annotiere ihn einmal, und das Objekt ist überall typisiert, wo es auftaucht:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* Der Lifespan ist ein `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`; `@asynccontextmanager` auf einem `async`-Generator gibt dir genau das.
* Was immer er per `yield` liefert, wird zu `ctx.lifespan_context`, und weil die Handler mit `ServerRequestContext[Catalog]` annotiert sind, funktionieren Autovervollständigung und Typprüfung für `.search(...)`.
* Er wird einmal betreten, wenn der Server startet, und einmal verlassen, wenn er stoppt. Start, Abbau und die Variante derselben Idee in `MCPServer` stehen in **[Lifespan](../handlers/lifespan.md)**.

Ohne ein `lifespan=` ist `ctx.lifespan_context` ein leeres `dict`.

## Eine eigene Methode {#a-method-of-your-own}

Der Konstruktor deckt die Methoden ab, die MCP definiert. `add_request_handler` deckt alles andere ab:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* Das erste Argument ist der Methoden-String. Benachrichtigungen haben ein Gegenstück, `add_notification_handler`.
* `params_type` ist das Modell, gegen das die eingehenden `params` validiert werden, **bevor** dein Handler läuft – eigene Methoden bekommen also *doch* die Validierung, die Tools nicht bekommen. Leite von `RequestParams` ab, damit das Feld `_meta` so geparst wird wie bei jeder anderen Methode.
* Der Handler gibt ein `BaseModel`, ein `dict` oder `None` zurück. Das SDK serialisiert es in das JSON-RPC-Ergebnis.

Ein ehrlicher Vorbehalt: Der High-Level-`Client` hat nur Verben für die Methoden, die MCP definiert, es gibt also kein `client.reindex()`. Eine Vendor-Methode ist für eine Gegenstelle gedacht, die bereits weiß, dass es sie gibt: ein Client, den du ebenfalls auslieferst, oder ein anderer deiner Dienste, der JSON-RPC spricht.

Eine Methode, die du nicht beanspruchen kannst:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

Der Handshake gehört dem Runner. `server/discover`, `ping` und jeden anderen Built-in darfst du ersetzen.

!!! tip
    `Server.middleware`, in dieser Fehlermeldung erwähnt, umhüllt **jede** eingehende Nachricht, `initialize` eingeschlossen. Wenn du Verkehr beobachten oder umschreiben willst, statt eine neue Methode zu beantworten, fang bei **[Middleware](middleware.md)** an.

## Die übrigen Handler {#the-other-handlers}

Jeder davon ist eine Idee, für die du jetzt das Vokabular hast; jeder hat seine eigene Seite.

* `on_call_tool`, `on_get_prompt` und `on_read_resource` dürfen statt ihres normalen Ergebnisses ein `InputRequiredResult` zurückgeben, um den Aufruf anzuhalten und den Client um Eingaben zu bitten; siehe **[Multi-Roundtrip-Requests](../handlers/multi-round-trip.md)** (multi-round-trip requests). Getreu dieser Ebene wird nichts für dich installiert: Wo `MCPServer` `requestState` standardmäßig versiegelt, geht hier der `request_state`, den du setzt, genau so über die Leitung, wie du ihn geschrieben hast, bis du dich mit `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` dafür entscheidest: eine Zeile (beide Namen lassen sich aus `mcp.server.request_state` importieren) für genau die Versiegelung und Verifizierung, die `MCPServer` vornimmt (**[`requestState` schützen](../handlers/multi-round-trip.md#protecting-requeststate)**).
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` haben dieselbe Form `(ctx, params) -> result` für die anderen Primitive.
* `on_subscriptions_listen` bedient den Stream `subscriptions/listen` aus 2026-07-28. Übergib einen `ListenHandler`, der auf einem `SubscriptionBus` aufgebaut ist, und veröffentliche Ereignisse aus deinen anderen Handlern auf dem Bus; die vollständige Zusammensetzung steht in **[Abonnements](../handlers/subscriptions.md)**.
* `server.streamable_http_app()` gibt dieselbe Starlette-App zurück wie die von `MCPServer`; stelle sie bereit, wie **[Den Server betreiben](../run/index.md)** jede andere ASGI-App bereitstellt. Hier unten gibt es kein `server.run(transport=...)`: `server.run(read_stream, write_stream, server.create_initialization_options())` treibt eine Verbindung über ein Paar Streams, und diese eine Zeile ist alles.

## Zusammenfassung {#recap}

* Der Low-Level-`Server` nimmt seine Handler als `on_*`-**Konstruktorparameter**; jeder Handler ist `async (ctx, params) -> result`.
* Du schreibst das `input_schema`-dict und du baust das `CallToolResult`. Nichts wird für dich abgeleitet, verpackt oder validiert.
* Eine Exception in einem Handler ist ein `-32603`-Protokollfehler. Ein Tool-Fehler, den das Modell lesen kann, ist ein `CallToolResult` mit `is_error=True`, das **du** zurückgibst.
* `_meta` auf dem Ergebnis richtet sich an die Client-Anwendung, nicht an das Modell.
* `Server[T]` ist generisch in dem, was sein Lifespan liefert; `ctx.lifespan_context` ist ein typisiertes `T`.
* `add_request_handler(method, params_type, handler)` bedient jede Methode. `initialize` ist reserviert.
* Die Capabilities, die ein `Server` ankündigt, leiten sich davon ab, welche Handler du registriert hast.

`Client(server)` hat beide Server identisch behandelt, weil sie dasselbe Protokoll *sind* – und genau darum geht es. Die nächste Schicht darunter ist gar keine Klasse: Es ist **[Middleware](middleware.md)**.
