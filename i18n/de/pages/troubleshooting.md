---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# Fehlerbehebung {#troubleshooting}

Jede Überschrift auf dieser Seite ist der exakte Text eines Fehlers, den das SDK erzeugt, gefolgt davon, was er bedeutet, und der Lösung in einem Schritt. Suche die letzte Zeile deines Tracebacks (oder deines Server-Logs) hier mit der Seitensuche des Browsers und lies nur diesen Eintrag.

Mehrere Einträge laufen gegen diesen einen Server: ein Tool und eine Ressource mit Template, die beide bei einer Stadt, die sie nicht kennen, eine Exception auslösen:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

Die Fehler, die diese Seite zitiert, sind echt: Die Testsuite des SDK selbst reproduziert jeden einzelnen.

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

Das ist kein MCP-Fehler. Es ist Rauschen von anyio, und dein eigentlicher Fehler steht in der **letzten Zeile** der Ausgabe.

`Client.__aenter__` startet eine Task-Group. anyio verpackt alles, was eine Task-Group verlässt, in eine `ExceptionGroup`. Deshalb kommt *jede* Exception, die einen `async with Client(...)`-Block verlässt – egal welche –, in einer solchen an:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

Damit machst du zwei Dinge:

1. **Unten lesen.** `MCPError: No forecast for 'Atlantis'.` ist der Fehler; suche *dessen* Text auf dieser Seite.
2. **Im Block abfangen.** Die `ExceptionGroup` erscheint nur, wenn die Exception das `async with` *verlässt*. Fängst du sie innerhalb ab, ist derselbe Fehler die schlichte `MCPError`, ganz ohne Gruppe:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    Ein Fehler beim *Verbindungsaufbau* (eine falsche URL, ein Server, der nicht läuft, der `421`
    weiter unten auf dieser Seite) entweicht aus dem `async with` selbst, es gibt also kein
    „Innen“, in dem du ihn abfangen könntest. Lies in diesen Fällen das Ende der Gruppe.

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` baut nur das Objekt. Verbunden wird erst mit `async with`, deshalb verweigert jede Methode den Dienst:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

Betritt den Kontextmanager. `__aenter__` ist die Verbindung:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` ist die Trennung – deshalb gibt es kein `client.close()`, das du vergessen könntest. **[Testen](get-started/testing.md)** baut genau auf diesem Muster auf.

## `Error executing tool <name>: <message>` und `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

Du liest ein **Ergebnis**, keine Exception. `call_tool` hat nichts ausgelöst und wird das bei einem fehlschlagenden Tool auch nie tun.

Rufe `forecast` für eine Stadt auf, die der Server nicht kennt, und die Exception, die es auslöst, kommt zurück, während der Request als *erfolgreich* markiert ist:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` hat dieselbe Form bei einem Namen, den der Server nie registriert hat, und ein ungültiges Argument wird genauso abgewiesen – anhand des Eingabeschemas des Tools, bevor deine Funktion überhaupt läuft.

Die Lösung liegt in deinem Client: **Prüfe `result.is_error`.** Ein `try/except` um `call_tool` fängt nichts davon ab, weil es nichts abzufangen gibt. Das ist Absicht, und es ist das Nützlichste auf dieser Seite, das du verinnerlichen solltest: Das *Modell* hat den Aufruf gewählt, also bekommt das Modell die Meldung und eine Chance, es erneut zu versuchen. Alles Weitere steht in **[Fehler behandeln](servers/handling-errors.md)**, einschließlich des `MCPError`-Pfads, der *tatsächlich* eine Exception auslöst.

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

Du hast `@mcp.tool` statt `@mcp.tool()` geschrieben. `tool()` ist eine Dekorator-*Fabrik*: Ohne die Klammern übergibt Python deine Funktion an deren Parameter `name=`.

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

Füge die Klammern hinzu. `@mcp.resource(...)` und `@mcp.prompt()` melden dasselbe beim selben Ausrutscher.

!!! note
    Das wird beim **Import** des Moduls ausgelöst, bevor sich ein Client verbindet. Ein Host, der
    deinen Server als *Start fehlgeschlagen* (oder *getrennt*) anzeigt statt als verbunden mit null
    Tools, hat also diese Form: Führe `python server.py` selbst aus und lies den Traceback. Ein
    Type-Checker fängt es ebenfalls ab: Eine Funktion ist kein gültiges `name=`.

## `Tool already exists: <name>` {#tool-already-exists-name}

Zwei Registrierungen haben denselben Tool-Namen verwendet. Die **erste** gewinnt, die zweite wird stillschweigend verworfen, und diese Warnung im *Server-Log* ist das einzige Signal:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` meldet ein `forecast`, und zwar `forecast_today`. Benenne eines der beiden um. `MCPServer(..., warn_on_duplicate_tools=False)` unterdrückt die Warnung, ohne das Ergebnis zu ändern, lass sie also eingeschaltet. Für Ressourcen und Prompts gilt dieselbe Regel mit derselben Log-Zeile (`Resource already exists:`, `Prompt already exists:`).

## Mein Host listet keine Tools auf {#my-host-lists-zero-tools}

Dafür gibt es keinen Fehlertext, und genau deshalb ist es schwer zu suchen. Das SDK entfernt nie ein registriertes Tool aus `tools/list`, arbeite dich also von innen nach außen vor:

* **Ist der Server überhaupt gestartet?** `@mcp.tool` ohne Klammern löst beim Import aus, und ein abgestürzter Server sieht in manchen Hosts einem leeren sehr ähnlich. Führe `python server.py` selbst aus.
* **Hängt das Tool an dem `mcp`, das der Host ausführt?** Ein zweites `MCPServer(...)` in einem anderen Modul ist ein anderer, leerer Server. Prüfe, welches Objekt der Befehl des Hosts tatsächlich importiert.
* **Teilen sich zwei Tools einen Namen?** Dann ist eines davon weg. Suche im Server-Log nach `Tool already exists:`.
* **Ist die Liste des Hosts nicht mehr aktuell?** Ein Tool, das nach dem Start hinzugefügt wird, erreicht nur Clients, die `notifications/tools/list_changed` verarbeiten. Den Host neu zu starten ist die grobe Lösung.
* **Hat etwas außerhalb des umgeleiteten Fensters nach `stdout` geschrieben?** Während des Betriebs leitet das SDK *geflushte* verirrte stdout-Ausgaben nach stderr um (nach bestem Bemühen: Eine Umgebung, die die Standard-Streams ersetzt, wird unverändert bedient). Ausgaben, die früher nach stdout geflusht wurden (ein Wrapper-Skript mit echo, ein `print()` beim Import in einem ungepufferten Prozess), oder ein gepuffertes `print()`, das beim Beenden des Interpreters geleert wird, landen aber auf dem Protokoll-Stream, und eine einzige Müllzeile kann den Host dazu bringen, die Verbindung zu schließen – was manche Hosts als Server ohne Inhalt darstellen. Logge stattdessen mit dem Modul `logging`. Der Rest der Checkliste auf Host-Seite steht auf **[Mit einem echten Host verbinden](get-started/real-host.md)**.

Ein „ungültiger“ Tool-Name steht *nicht* auf dieser Liste: Ein nicht konformer Name loggt eine Warnung, aber das Tool wird trotzdem registriert und aufgelistet.

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

Der Server hat den HTTP-Request rundheraus abgelehnt, mit einem Body, der kein JSON-RPC ist, sodass der Python-`Client` dir nichts Besseres zeigen kann als diesen Platzhalter.

Die mit Abstand häufigste Ursache ist ein frisch bereitgestellter Streamable-HTTP-Server. `streamable_http_app()` (und `mcp.run("streamable-http")`) ohne `transport_security=` verwendet standardmäßig den **DNS-Rebinding-Schutz**: Es werden nur Requests akzeptiert, deren `Host`-Header localhost ist. Das ist der richtige Standardwert auf deinem Laptop und der falsche hinter einem echten Hostnamen:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

Stelle das bereit, richte einen Client darauf, und die Verbindung scheitert beim Handshake:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

Die Wörter, die der Server tatsächlich gesendet hat, `421` und `Invalid Host header`, erreichen dich nie: Der 421-Body hat kein `Content-Type: application/json`, also kann der Client ihn nicht parsen. Sie stehen im **Log des Servers**, und dort schaust du als Nächstes nach:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

Die Lösung ist `transport_security=`. Setze den Hostnamen, den du tatsächlich bedienst, auf die Allowlist:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    Das ist die ganze Änderung. Derselbe Client verbindet sich jetzt, handelt `2026-07-28` aus
    und ruft `forecast` auf.

**[Bereitstellen und skalieren](run/deploy.md)** erklärt, was jedes Feld bedeutet, den Fall mit Reverse-Proxy und alles andere, was sich beim Bereitstellen ändert. Und `421 Misdirected Request` / `Invalid Host header` direkt darunter ist derselbe Fehler, von der anderen Seite gesehen.

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

Das ist `Server returned an error response`, gesehen von allem, was *nicht* der Python-`Client` ist: curl, der Netzwerk-Tab eines Browsers, das Access-Log eines Reverse-Proxys oder ein anderes SDK.

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` ist HTTPs eigene Reason-Phrase für den Status; `Invalid Host header` ist der Response-Body des SDK; und der Python-`Client` stellt dasselbe Ereignis als `Server returned an error response` dar. Alle drei sind eine einzige Ablehnung. Die Prüfung läuft gegen den **`Host`-Header, den der Request trägt**, nicht gegen die Adresse, an die der Server gebunden ist. Ein Reverse-Proxy, der den öffentlichen Hostnamen weiterleitet, löst sie also genauso aus wie ein direkter Client.

Die Lösung ist dasselbe `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` wie unter `Server returned an error response`. Zwei Randfälle sind erwähnenswert:

* Ein `allowed_hosts`-Eintrag ist ein exakter String. `"mcp.example.com"` passt auf einen `Host`-Header ohne Port und `"mcp.example.com:*"` auf jeden expliziten Port. Führe beide auf.
* Ein `403` mit dem Body `Invalid Origin header` ist die verwandte Prüfung des `Origin`-Headers. Sie greift nur bei Browsern (nichts anderes sendet `Origin`), und `allowed_origins=` ist ihre Allowlist.

Alles Weitere steht in **[Bereitstellen und skalieren](run/deploy.md)**, auch dazu, wann das Abschalten der Prüfung die ehrliche Konfiguration ist.

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

Deine MCP-App ist in eine andere ASGI-App eingehängt, und nichts hat ihren **Session-Manager** gestartet.

`mcp.streamable_http_app()` gibt eine Starlette-App zurück, deren eigener Lifespan (Start- und Stopp-Phase) den Manager startet, und `uvicorn server:app` führt diesen Lifespan für dich aus. Aber Starlette **führt nie den Lifespan einer eingehängten Sub-App aus**. Sobald die App also in einem `Mount` steckt, startet der Manager nie, und der erste Request fliegt dir um die Ohren:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

Der Server startet. Die Route wird aufgelöst. Dann gibt `uvicorn` bei jedem Request Folgendes aus:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

Der Client sieht einen 500. Die Lösung ist ein Lifespan auf der **Host**-App, der `mcp.session_manager.run()` betritt:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

**[In eine bestehende App einbinden](run/asgi.md)** ist die Seite dazu, einschließlich mehrerer Server in einer App und FastAPI. Zwei benachbarte Strings aus derselben Klasse:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` Der Manager ist zum einmaligen Gebrauch; wer den Lifespan derselben App zweimal betritt, trifft darauf.
* `mcp.session_manager` existiert erst, **nachdem** `streamable_http_app()` aufgerufen wurde. Baue also zuerst die Routen und fasse den Manager nur innerhalb des Lifespans an.

## `MCPError: Session not found` {#mcperror-session-not-found}

Der Server erkennt die `Mcp-Session-Id`, die dein Client gesendet hat, nicht – fast immer, weil der Server **neu gestartet** wurde (oder du zu einer anderen Instanz geroutet wurdest). Sessions leben im Speicher dieses einen Prozesses.

Es gibt keinen Server-Bug zu finden. Die HTTP-Response ist ein `404`, dessen Body JSON-RPC *ist*, deshalb zeigt dir der Python-`Client` – anders als beim `421` oben – diese hier wörtlich:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

Die Lösung ist, dich neu zu verbinden: Verlasse den `async with Client(...)`-Block und betritt einen neuen, der eine frische Session aushandelt. Für einen langlebigen Client heißt das, `MCPError` um deine Aufrufe herum abzufangen und bei dieser Meldung neu zu verbinden, statt es in einer toten Session erneut zu versuchen.

Passiert es *ohne* Neustart, betreibst du mehr als einen Worker ohne Sticky Sessions: Jeder Worker hält seine eigene Session-Tabelle, sodass ein Request, der zum falschen geroutet wird, hier landet. **[Bereitstellen und skalieren](run/deploy.md)** und **[Legacy-Clients unterstützen](run/legacy-clients.md)** behandeln dieses Thema und seine beiden Lösungen (Sticky Routing oder `stateless_http=True`).

Für alle, die den Server betreiben, lautet die passende Log-Zeile `Rejected request with unknown or expired session ID: <id>`. Sie wird auf `INFO` geloggt, ist also bei der üblichen `WARNING`-Schwelle unsichtbar. Sie direkt nach einem Deployment stoßweise zu sehen ist normal; jeder verbundene Client verbindet sich neu.

## `MCPError: Method not found` {#mcperror-method-not-found}

Eine Seite hat einen JSON-RPC-Request gesendet, für den die andere keinen Handler hat, und `e.error.data` nennt die Methode. Die übliche Ursache sind **unterschiedliche Protokollgenerationen**: eine Methode, die in einer Protokollrevision existiert und in der anderen nicht, gesendet an ein Gegenüber auf der falschen – etwa ein `resources/subscribe` der `2025`er-Generation, das auf einer `2026-07-28`-Verbindung ankommt, oder ein nur in `2026` vorhandenes `subscriptions/listen`, gesendet von einem Client, der auf `mode="legacy"` festgelegt ist. **[Protokollversionen](protocol-versions.md)** ist die Karte, welche Seite was spricht, und die andere ehrliche Ursache (eine optionale Capability, für die du nie einen Handler registriert hast) steht auf **[Vervollständigungen](servers/completions.md)**.

Eines erzeugt diesen Fehler **nicht**, obwohl es ein Request ist, den das moderne Protokoll entfernt hat: ein Tool, das `ctx.elicit()` auf einer `2026-07-28`-Verbindung aufruft. Der Server weigert sich, diesen Request überhaupt zu *senden*, sodass du stattdessen `Cannot send 'elicitation/create': ...` bekommst, weiter unten auf dieser Seite.

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

Dein Server möchte die Person am Host etwas fragen, und dieser Client hat nie gesagt, dass man ihn fragen kann.

Ein Resolver für Elicitation (Rückfrage bei der Person am Host) lehnt von vornherein ab, wenn der verbundene Client keine Form-Elicitation deklariert hat, und `e.error.data` nennt genau, was fehlt:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

Übergib `elicitation_callback=` an `Client(...)`. Den Callback zu registrieren *ist* die Deklaration der Capability; einen zweiten Schalter gibt es nicht:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[Client-Callbacks](client/callbacks.md)** listet die anderen auf (`sampling_callback`, `list_roots_callback`), von denen jeder auf dieselbe Weise eine Deklaration ist.

!!! info
    `-32021` ist `MISSING_REQUIRED_CLIENT_CAPABILITY`, einer von drei Fehlercodes, die die
    Spezifikation 2026-07-28 hinzufügt. Keiner davon ist eine Exception-Klasse: Alle kommen als
    `MCPError` an, und `e.error.code` ist die Stelle zum Nachsehen. `mcp.types` exportiert die
    Konstanten. Die beiden anderen sind `-32020` `HEADER_MISMATCH` (ein HTTP-Header widerspricht
    dem Request-Body, den er begleitet) und `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (der Request
    nannte eine Version, die dieser Server nicht spricht). Ein konformer SDK-Client kann keinen von
    beiden erzeugen; siehst du einen, schau dir an, was zwischen deinem Client und deinem Server
    Requests umschreibt.

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

Dieselbe Lücke wie bei `Client did not declare the form elicitation capability ...`, formuliert von den Pfaden, die nicht vorab prüfen: Der Server brauchte eine Antwort auf eine Elicitation, und der verbundene Client hat keinen `elicitation_callback` registriert.

Du siehst diese bei `ctx.elicit()` auf einer Legacy-Verbindung, und auf jeder beliebigen Verbindung bei einer zurückgegebenen Multi-Roundtrip-Frage (multi-round-trip, **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)**), die einen Client ohne Callback zum Beantworten erreicht. Die Lösung ist identisch: Übergib `elicitation_callback=` an `Client(...)`. Es gibt keine Variante von „die Person wurde nicht gefragt“, die dein Tool als `decline` erhält; ein Client, der nicht gefragt werden kann, ist ein fehlgeschlagener Aufruf, also entwirf deine Tools entsprechend.

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

Dein Handler hat versucht, den Client mitten im Request zu erreichen, auf einer Verbindung, deren Aufruf keinen Rückkanal (back-channel) hat, der einen Request vom Server tragen kann. Drei Server-Konfigurationen bringen einen Aufruf in diese Lage.

**Eine `2026-07-28`-Verbindung: jeder Transport, immer.** Das moderne Protokoll kennt überhaupt keine vom Server initiierten Requests, deshalb weigert sich der Server, bevor irgendetwas gesendet wird. `ctx.elicit()` innerhalb eines Tools ist der klassische Weg, dem zu begegnen (schon beim allerersten In-Memory-Test, denn `Client(server)` handelt ungefragt `2026-07-28` aus), und `elicitation_callback=` zu übergeben ändert nichts, weil nie ein Request beim Client ankommt, den er beantworten könnte:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**Eine Legacy-Verbindung auf einem Server mit `stateless_http=True`.** Zustandslosigkeit heißt, jeder Request ist seine eigene Welt: keine Session, kein Stream vom Server zum Client und damit nichts, wohin ein `elicitation/create` (oder `sampling/createMessage` oder `roots/list`) gesendet werden könnte – selbst in der Generation, die sie kennt:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**Eine Legacy-Verbindung auf einem Server mit `json_response=True`.** Das `POST` wird mit einem einzigen JSON-Body beantwortet, und ein einziger Body trägt nur die Response, sodass der Request-gebundene Stream, den ein `ctx.elicit()` mitten im Request braucht, auch hier nicht existiert. Die Session, ihre `Mcp-Session-Id` und ihr eigenständiger Stream sind alle noch da; nur der Request-gebundene Kanal fehlt.

Die Meldung nennt die Methode, die sie nicht senden konnte. `NoBackChannelError` ist die Klasse, die der Server auslöst, aber über die Leitung geht nur die Basisklasse `MCPError`, sodass der Satz oben die letzte Zeile deines Tracebacks ist, nicht der Klassenname.

Für einen `2026-07-28`-Client ist die Lösung in allen drei Fällen dieselbe: Greife nicht mitten im Aufruf zurück. Verschiebe die Frage in einen **Resolver** (oder gib selbst ein `InputRequiredResult` zurück), und sie wird Teil der *Response*, die jede Verbindung tragen kann:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

Dieselbe Frage, derselbe `elicitation_callback` auf dem Client. Der Unterschied liegt unter der Haube: Mit einem Resolver kann der Server die Frage aus dem Aufruf *zurückgeben*, statt sie zu pushen, sodass nie etwas vom Server zum Client fließt. Das rettet jeden `2026-07-28`-Client, in welcher der drei Konfigurationen sich der Server auch befindet. Ein *Legacy*-Client wird durch die Umschreibung allein nicht gerettet: `2025-11-25` hat keine Möglichkeit, eine Frage zurückzugeben, also sendet der Resolver auf einer Legacy-Verbindung weiterhin `elicitation/create` über den Request-gebundenen Kanal und braucht weiterhin einen Server, der ihn behält – weder `stateless_http=True` noch `json_response=True`. **[Elicitation](handlers/elicitation.md)** behandelt Resolver; **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)** behandelt, was auf der Leitung passiert.

!!! check
    Das Tool mit `ctx.elicit()` ist nicht falsch, es ist *vor 2026*. Verbinde dich mit
    `mode="legacy"` (der klassische `initialize`-Handshake, Spezifikation `2025-11-25` und früher)
    mit einem Server, der weder `stateless_http=True` noch `json_response=True` ist, und es
    funktioniert, weil der Kanal vom Server zum Client dort existiert.
    **[Protokollversionen](protocol-versions.md)** ist die Seite dazu, was jede Version hat.

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

Der Server konnte das `requestState`-Token, das dein Client zurückgespielt hat, nicht verifizieren und hat die Runde deshalb abgelehnt.

`requestState` ist das opake Resume-Token, das ein **[Multi-Roundtrip](handlers/multi-round-trip.md)**-Aufruf zwischen den Etappen trägt. `MCPServer` versiegelt es auf dem Weg nach draußen und verifiziert jedes Echo, und er verifiziert *jedes* eingehende `request_state` bei `tools/call`, `prompts/get` und `resources/read`, selbst für einen Handler, der nie eines ausstellt. Ein Token, das dieser Prozess nicht versiegelt hat, wird also abgelehnt, wo immer es landet:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

Die Meldung ist absichtlich festgeschrieben: Die Leitung verrät nie, welche Prüfung fehlgeschlagen ist. Der Grund geht ins **Server-Log**, und ihn zu lesen ist die ganze Diagnose:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

Die Gründe, die du tatsächlich sehen wirst:

* **`unknown key`** ist der, auf den es ankommt. Der Standardschlüssel zum Versiegeln wird beim Prozessstart erzeugt, also wurde ein Retry, der auf einem **anderen Worker**, einer anderen Instanz hinter einem Load Balancer oder demselben Server **nach einem Neustart** landet, unter einem Schlüssel versiegelt, den dieser Prozess nie hatte. Das ist kein Angreifer; das ist der Standardwert, der auf mehr als einen Prozess trifft.
* **`audience`**: Das Token wurde von einer Instanz mit einem *anderen Servernamen* versiegelt. Der Name ist der standardmäßige Audience-Claim des Siegels, also muss eine Flotte neben den Schlüsseln auch den Namen teilen (oder ein explizites `RequestStateSecurity(audience=...)` setzen).
* **`expired`**: Die Runde hat länger gedauert als die `ttl` des Siegels, die 600 Sekunden beträgt und pro Runde gilt, nicht pro Aufruf.
* **`malformed`** / **`codec error`**: Das Token wurde unterwegs verändert oder war nie ein versiegeltes Token.
* **`request binding`**: Das Token kam mit einem anderen Tool, anderen Argumenten oder einer anderen Methode zurück.

Die Lösung für mehrere Prozesse ist ein Argument (die*selben* `keys` auf jeder Instanz) plus etwas, das gar kein Argument ist: derselbe Server*name* (oder ein explizites gemeinsames `audience=`).

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` versiegelt; jeder Schlüssel in der Liste verifiziert, und genau das ermöglicht Rotation ohne Ausfallzeit. **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md#protecting-requeststate)** erklärt, was das Siegel schützt, und die Rotationsabfolge, und **[Bereitstellen und skalieren](run/deploy.md)** geht den ganzen Fehlerfall mit zwei Workern und seine zweiteilige Lösung durch.

!!! tip
    `keys=[...]` lehnt einen schwachen Schlüssel sofort ab, mit einer ungewöhnlich hilfreichen
    Meldung:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    Tu, was sie sagt.

## Kommst du nicht weiter? {#still-stuck}

* Steht eine Meldung, die das SDK erzeugt hat, nicht auf dieser Seite, ist das ein Dokumentationsfehler, der für sich genommen eine Meldung wert ist.
* Durchsuche den [Issue-Tracker](https://github.com/modelcontextprotocol/python-sdk/issues); die meisten Fehlertexte, die dort auftauchen, hat schon jemand aufgeschrieben.
* Nichts gefunden? [Eröffne ein Issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml) mit dem vollständigen Traceback oder frage in [#python-sdk-dev auf dem MCP-Contributors-Discord](https://discord.gg/6CSzBmMkjX).

## Zusammenfassung {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` ist nie der Fehler. Lies die **letzte Zeile**; fängst du `MCPError` *innerhalb* des `async with Client(...)`-Blocks ab, entfällt die Verpackung komplett.
* `call_tool` löst bei einem fehlschlagenden Tool keine Exception aus. `Error executing tool ...` und `Unknown tool: ...` sind Ergebnisse: Prüfe `result.is_error`.
* `Client must be used within an async context manager` -> verwende `async with`. `Use @tool() instead of @tool` -> füge die Klammern hinzu.
* `Tool already exists:` im Server-Log ist das einzige Zeichen, dass zwei gleichnamige Tools zu einem zusammengefallen sind.
* Ein 421, drei Schreibweisen: `Server returned an error response` (der Python-`Client`), `421 Misdirected Request` / `Invalid Host header` (alles andere), `Invalid Host header: <host>` (das Server-Log). Lösung: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`.
* `Task group is not initialized` -> eine eingehängte App, deren Host-Lifespan nie `mcp.session_manager.run()` betreten hat.
* `Session not found` -> der Server wurde neu gestartet; verbinde dich neu.
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` braucht einen Kanal vom Server zum Client: Eine `2026-07-28`-Verbindung hat nie einen, `stateless_http=True` nimmt den Legacy-Kanal weg, und `json_response=True` nimmt den Request-gebundenen weg. Verwende einen Resolver (ein Legacy-Client braucht außerdem einen Server, der den Kanal behält). Sein Nachbar `Method not found` ist ein Request für eine Methode, die die Protokollrevision der anderen Seite nicht hat.
* `Client did not declare the form elicitation capability ...` und `Elicitation not supported` -> dem Client fehlt `elicitation_callback=`.
* `Invalid or expired requestState` sagt auf der Leitung nie, warum. Das Server-Log schon; `unknown key` heißt: Teile `RequestStateSecurity(keys=[...])` über alle Worker hinweg.
