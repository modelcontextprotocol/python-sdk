---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# Was ist neu in v2 {#whats-new-in-v2}

In v2 ist zweierlei auf einmal passiert. Das **SDK wurde neu gebaut**: eine neue Engine unter Client und Server, ein vollwertiger `Client` und eine Reihe von Umbenennungen, auf die eine v1-Codebasis beim ersten Import stößt. Und das **Protokoll hat sich bewegt**: v2 spricht die Revision 2026-07-28 von MCP, die den Verbindungs-Handshake, die Session und jeden vom Server ausgehenden Request entfernt, ohne die Clients im Stich zu lassen, die du bereits hast.

Diese Seite ist der Rundgang durch beide Hälften: ein Abschnitt pro Schlagzeile, jeder endet bei der Seite, zu der das Thema gehört. Sie ist nicht die Portierungsanleitung. Das ist der **[Migrationsleitfaden](migration.md)**: jede inkompatible Änderung, mit Code vorher und nachher.

!!! note "v2 ist die stabile Linie"
    `pip install mcp` installiert 2.x, und **[Installation](get-started/installation.md)** hat die
    Installationszeile zum Kopieren. Wenn irgendetwas in v2 kaputtgeht, dich überrascht oder ausbremst,
    [sag uns Bescheid](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

## Das SDK: von v1 zu v2 {#the-sdk-v1-to-v2}

### `FastMCP` heißt jetzt `MCPServer` {#fastmcp-is-now-mcpserver}

Die High-Level-Serverklasse wurde umbenannt, ihr Modul gleich mit. Das ist das Erste, worauf jeder v1-Server stößt, denn der alte Importpfad ist entfernt, nicht bloß veraltet:

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

Für einen mit Dekoratoren gebauten Server ist das auch schon der größte Teil der Portierung. `@mcp.tool()`, `@mcp.resource()` und `@mcp.prompt()` akzeptieren, was sie in v1 akzeptiert haben (`@mcp.resource()` bekommt ein optionales Schlüsselwort `security=` dazu), und das Eingabeschema kommt weiterhin aus deinen Type Hints. An den Rändern: Alles unter `mcp.server.fastmcp.*` liegt jetzt unter `mcp.server.mcpserver.*`, `ctx.fastmcp` heißt `ctx.mcp_server`, `get_context()` ist entfernt (deklariere stattdessen einen Parameter `ctx: Context`), und die Exception-Basisklasse `FastMCPError` heißt `MCPServerError`. Die Importtabelle steht im **[Migrationsleitfaden](migration.md#fastmcp-renamed-to-mcpserver)**.

### `Resolve`: der neue Weg, die Person am Host nach Eingaben zu fragen {#resolve-the-new-way-to-ask-the-user-for-input}

Nicht alles, was ein Tool braucht, sollte vom Modell kommen. Neu in v2: Ein Tool-Parameter, der mit `Resolve(fn)` annotiert ist, wird stattdessen von einer Funktion gefüllt, die du schreibst – unsichtbar für das Modell –, und diese Funktion kann `Elicit(...)` zurückgeben, um der Person am Host eine Frage zu stellen. Das ist der bevorzugte Weg, mitten im Aufruf irgendetwas vom Client zu bekommen: Das SDK transportiert die Frage über den Mechanismus, den die Verbindung jeweils unterstützt – bei einem Legacy-Client ein Live-Request per Elicitation (Rückfrage bei der Person am Host), bei 2026-07-28 ein Multi-Roundtrip (multi-round-trip) –, sodass ein einziger Tool-Body beide Generationen bedient. Die Seite dazu ist **[Abhängigkeiten](handlers/dependencies.md)**.

!!! note
    Die beiden anderen Formen bleiben, wenn du sie brauchst: `ctx.elicit()` funktioniert weiterhin für
    Clients auf Legacy-Verbindungen (**[Elicitation](handlers/elicitation.md)**), und ein Handler kann
    selbst ein `InputRequiredResult` zurückgeben und die Runden von Hand steuern – so reisen bei
    2026-07-28 auch Sampling- und Roots-Requests (**[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)**).

### Ein vollwertiger `Client` {#a-first-class-client}

v1 gab dir drei verschachtelte Schichten: einen Transport-Kontextmanager, der rohe Streams liefert, eine darum gewickelte `ClientSession` und ein von Hand aufgerufenes `await session.initialize()`. v2 hat ein einziges Objekt:

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` nimmt ein Server-Objekt (im Speicher, ohne Transport: das ist der Testansatz), eine URL (Streamable HTTP) oder einen beliebigen Transport-Kontextmanager wie `stdio_client(...)`. Das Betreten von `async with` verbindet und handelt die Protokollversion aus, welche Generation der Server auch spricht; `client.server_capabilities` und `client.protocol_version` sind danach einfach da, ebenso `client.server_info`, wenn der Server sich zu erkennen gibt (das ist jetzt `Implementation | None`, weil die Identität in der 2026er-Generation optional ist). Die Sampling- und Elicitation-Callbacks, die du in v1 registriert hast, funktionieren weiter (ihre Bodies sehen dieselbe Umbenennung der Attribute auf snake_case wie alles andere auf dieser Seite), sie beantworten jetzt außerdem die Requests-in-Results im 2026er-Stil (unten), und sie laufen nebenläufig statt nacheinander. `ClientSession` liegt für alle, die die Low-Level-Oberfläche wollen, weiterhin darunter, und `client.session` reicht sie dir; auch sie hat sich bewegt (sie läuft auf der neuen Dispatcher-Engine, und einige ihrer eigenen Signaturen haben sich geändert), lies also den **[Migrationsleitfaden](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)**, bevor du hinabsteigst.

**[Der Client](client/index.md)** stellt ihn vor, **[Client-Transporte](client/transports.md)** behandelt die drei Verbindungsformen, **[Client-Callbacks](client/callbacks.md)** die Callbacks selbst, und **[Testen](get-started/testing.md)** zeigt das In-Memory-Muster, das den Helfer `create_connected_server_and_client_session()` aus v1 ersetzt.

### Der Low-Level-`Server` wurde neu gebaut, nicht umbenannt {#the-low-level-server-was-rebuilt-not-renamed}

Wenn du auf der JSON-RPC-Ebene arbeitest, ist das der Teil von v2, bei dem „alles anders ist“. Hier ist derselbe Server mit einem Tool in beiden Varianten; klicke auf die Marker, um zu sehen, was sich verschoben hat.

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. Handler werden mit Dekoratoren registriert (aufgerufen, mit Klammern), jederzeit, nachdem der Server existiert.
2. Du gibst eine bloße `list[Tool]` zurück, und das SDK verpackt sie in ein `ListToolsResult`.
3. Felder sind in Python camelCase, und das Schema wird **durchgesetzt**: Das SDK validiert die `call_tool`-Argumente per jsonschema dagegen, bevor deine Funktion läuft – deshalb ist `arguments["query"]` unten sicher.
4. Ein einziger `call_tool`-Handler bedient jedes Tool, und er erhält den Tool-Namen und die bereits validierten Argumente, ausgepackt und nie `None`.
5. Durch das Auslösen einer Exception signalisiert ein v1-Tool einen Fehlschlag: Jede Exception wird abgefangen und als `CallToolResult(isError=True)` mit `str(e)` als Text zurückgegeben, sodass das aufrufende Modell diese Meldung liest und es erneut versuchen kann.
6. Der Kontext kommt aus einer umgebenden ContextVar, die mitten im Request über das Server-Objekt erreicht wird.
7. Bloße Content-Blöcke werden für dich in ein `CallToolResult` verpackt.

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Felder sind jetzt snake_case, und das Schema wird **bekannt gegeben, aber nie angewendet**: Nichts prüft die Argumente, bevor dein Handler läuft.
2. Jeder Handler hat dieselbe Form: `async (ctx, params) -> result`. Der Kontext ist das erste Argument (`ctx.session`, `ctx.request_id`, `ctx.protocol_version` liegen darauf); dorthin ist `server.request_context` gewandert.
3. Du baust das vollständige `ListToolsResult` selbst. Eine bloße Liste zurückzugeben ist jetzt ein serverseitiger `TypeError`, nichts, was das SDK verpackt.
4. Typisierte Params hinein (`params.name`, `params.arguments`), ein vollständiges Result hinaus. Nichts wird für dich ausgepackt, verpackt oder umgewandelt.
5. Dieselbe Prüfung, anderes Verb. Ein `ValueError` käme hier beim Modell als undurchsichtiges `-32603` an (siehe unten), daher wird ein absichtlicher Fehler auf der Leitung als `MCPError` ausgelöst: Er geht mit Code und Meldung unverändert durch, und `-32602` mit diesem Text ist die eigene Antwort der Spezifikation für ein unbekanntes Tool.
6. `params.arguments` kann `None` sein; v1 setzte es auf `{}`, bevor dein Code es je zu sehen bekam. Ohne Validierung vor dem Handler ist diese Zeile tragend.
7. Eine hier ausgelöste unerwartete Exception wird zu einem **bereinigten** Protokollfehler, `-32603` `"Internal server error"`: Das Modell sieht die Meldung nie. Für einen Fehlschlag, den das Modell lesen und auf den es reagieren soll, gib `CallToolResult(is_error=True, ...)` zurück.
8. Handler sind Konstruktorargumente, die Oberfläche des Servers ist also in dem Moment vollständig, in dem er existiert; `add_request_handler()` ist der Notausgang nach der Konstruktion und die Tür zu eigenen Methoden.

Das Beispiel ist das Muster. Allgemeiner: Jeder Handler hat dieselbe Form, mit typisierten Params hinein und einem vollständigen Result-Typ hinaus; die alte jsonschema-Prüfung der Tool-Argumente ist entfernt; eine Exception ist ein Protokollfehler, nie ein Tool-Result mit `is_error=True`; und die umgebende ContextVar `server.request_context` ist entfernt. Eigene Methoden mit Vendor-Namespace sind über `add_request_handler(method, params_type, handler)` vollwertig unterstützt; das validiert eingehende Params gegen dein Modell, bevor dein Handler läuft. Und eine `middleware`-Liste (bewusst als vorläufig markiert) umhüllt jede eingehende Nachricht und ersetzt die privaten `_handle_*`-Methoden, die früher überschrieben wurden.

Unter der Haube wurde die `BaseSession`-Empfangsschleife aus v1 durch eine Dispatcher-Engine ersetzt, die Client und Server sich jetzt teilen, und sie macht mehrere Dinge auf dieser Seite gleichzeitig wahr: Ein einziges `Server`-Objekt bedient beide Protokollgenerationen, `Client(server)` dispatcht im Prozess ohne JSON-RPC-Framing, und ein Client-Request, der in den Timeout läuft, bricht jetzt tatsächlich den serverseitigen Handler ab.

Die Seite dazu ist **[Der Low-Level-Server](advanced/low-level-server.md)**; der **[Migrationsleitfaden](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** geht jeden entfernten Hook durch. Wenn du nie unter `MCPServer` hinabgestiegen bist, betrifft dich nichts davon.

### Die Typen auf der Leitung sind nach `mcp-types` umgezogen, und jedes Feld ist snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

Die Protokolltypen leben jetzt in einer eigenen Distribution, `mcp-types`. Sie hängt von nichts außer pydantic und typing-extensions ab, sodass ein Gateway, ein Proxy oder ein Codegenerator die Formen, die MCP über die Leitung schickt, verwenden kann, ohne einen HTTP-Stack zu installieren: Ein solches Projekt installiert `mcp-types` und importiert `mcp_types`. `mcp` selbst hängt von diesem Paket in einer exakten Version ab und reicht es weiter, sodass Code, der vom SDK abhängt, weiterhin `import mcp.types as types` und `from mcp.types import Tool` schreibt (ein dauerhafter Alias, jeder Name dasselbe Objekt) und nur seine eine echte Abhängigkeit deklariert, `mcp`. Die Faustregel: Importiere über das Paket, von dem du tatsächlich abhängst.

Auf diesen Typen ist jedes Python-Attribut jetzt snake_case: `result.is_error`, `tool.input_schema`, `listing.next_cursor`. Das JSON auf der Leitung ist camelCase, genau wie zuvor; nur die Schreibweise der Attribute hat sich geändert. Zwei strengere Standardwerte kommen mit: Unbekannte Felder werden ignoriert statt durchgereicht (lege Zusätzliches in `_meta` ab), und beide Seiten validieren den Verkehr gegen die Protokollversion, die sie ausgehandelt haben. Die Umbenennungstabelle steht im **[Migrationsleitfaden](migration.md#field-names-changed-from-camelcase-to-snake_case)**.

### Die Transportkonfiguration ist nach `run()` umgezogen {#transport-configuration-moved-to-run}

Bei `MCPServer(...)` geht es darum, was dein Server *ist*: sein Name, seine Instruktionen, sein Lifespan, seine Auth. Wie er *ausgeliefert* wird, gehört jetzt zu `run()` und den App-Buildern; dorthin sind `host`, `port`, `stateless_http`, `json_response`, die Endpunktpfade und `transport_security` gewandert (`MCPServer("x", port=9000)` ist ein `TypeError`). Die Overloads sind pro Transport typisiert, dein Editor sagt dir also, welche Optionen `stdio` nimmt und welche `streamable-http`. Eine Entfernung, die du kennen solltest: `mount_path` ist weg; die ASGI-App zu mounten ist der unterstützte Weg, unter einem Präfix auszuliefern.

**[Den Server betreiben](run/index.md)** behandelt die Optionen; **[In eine bestehende App einbinden](run/asgi.md)** das Mounten.

### Verhalten, das sich ohne Importfehler ändert {#behavior-that-changes-without-an-import-error}

Die Umbenennungen machen sich selbst bemerkbar. Diese Änderungen nicht:

* **Synchrone Funktionen laufen auf einem Worker-Thread.** Ein `def`-Tool (oder eine Ressource, ein Prompt oder ein Resolver) blockiert die Event-Loop nicht mehr; der Preis dafür ist, dass sein Body nicht mehr *auf* dem Event-Loop-Thread läuft, was für threadgebundenen Code eine Rolle spielt. `async def`-Handler sind nicht betroffen. **[Migrationsleitfaden](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**.
* **Ein in einem Tool ausgelöster `MCPError` (in v1 `McpError`) ist jetzt ein Protokollfehler.** Das Modell sieht ihn nie. Jede andere Exception wird weiterhin zu einem Result mit `is_error=True`, das das Modell lesen und auf das es reagieren kann. Die Aufteilung steht in **[Fehler behandeln](servers/handling-errors.md)**.
* **Results werden validiert, bevor sie hinausgehen.** Ein von Hand gebautes `Tool`, dessen `input_schema` `{}` ist, lässt jetzt `tools/list` fehlschlagen (die Spezifikation verlangt `"type": "object"`). Server, die auf `@mcp.tool()` aufbauen, sehen das nie; das SDK schreibt ihre Schemas.
* **Dein Client validiert, was er empfängt.** `list_tools()` und `call_tool()` prüfen die Antwort des Servers gegen die ausgehandelte Protokollversion, sodass ein nicht ganz valider Server, den das nachsichtige Parsen von v1 tolerierte, jetzt `pydantic.ValidationError` auslöst. Wenn du dich mit Servern verbindest, die du nicht kontrollierst, rechne damit, dass du sie findest; die Details stehen im **[Migrationsleitfaden](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)**.
* **URI-Templates sind jetzt echtes RFC 6570.** `{+path}`, `{?query}` und Verwandte funktionieren, der Abgleich ist exakt statt Regex-locker, und Path Traversal in extrahierten Werten wird standardmäßig abgelehnt. Strengere Templates schlagen beim Dekorieren fehl, nicht beim ersten Request. **[URI-Templates](servers/uri-templates.md)**.
* **Der Lifespan bei Streamable HTTP läuft einmal**, beim Start, und sein Zustand wird von jeder Session und jedem Request geteilt. In v1 lief er einmal pro Session und unter `stateless_http=True` einmal pro Request. Pools und Caches, die in einem Lifespan gebaut werden, werden drastisch billiger; alles, was dort eine Ressource pro Verbindung beschafft hat, gehört jetzt in den Handler-Body. **[Lifespan](handlers/lifespan.md)**.
* **`mcp dev` und `mcp install` pinnen die Umgebung, die sie starten,** auf deine installierte SDK-Version. Beide Befehle führen deinen Server in einer frischen `uv run --with ...`-Umgebung aus, die `mcp` früher auf das neueste stabile Release auflöste statt auf die Version, gegen die du entwickelst. **[Migrationsleitfaden](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**.
* **Der HTTP-Client ist jetzt `httpx2`, nicht `httpx`.** Der Abhängigkeitswechsel ändert, was dein Code abfängt und übergibt (`httpx2.AsyncClient`, `httpx2.ConnectError`), und er ändert, wie TLS-Zertifikate geprüft werden: `httpx2` validiert über `truststore` gegen den Trust Store des Betriebssystems statt gegen die gebündelte CA-Liste von certifi. Die meisten Umgebungen merken davon nichts; ein minimaler Container ohne System-CA-Store oder eine private CA, die nur das Bundle von certifi kannte, scheitert nun beim TLS-Handshake. Setze `SSL_CERT_FILE`/`SSL_CERT_DIR` oder übergib deinem Client `verify=ssl_context`. **[Migrationsleitfaden](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**.

### Komplett entfernt {#removed-outright}

Jeder dieser Punkte ist ein Abschnitt im **[Migrationsleitfaden](migration.md)**:

* Der **WebSocket-Transport**, beide Seiten, und das Extra `mcp[ws]`. Er war nie Teil der MCP-Spezifikation.
* Die **experimentelle Tasks**-API (`mcp.*.experimental`). 2026-07-28 verlagert Tasks aus dem Kernprotokoll in eine offizielle Erweiterung ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)), die dieses SDK noch nicht implementiert.
* `mcp.shared.version`, `mcp.shared.progress` und `mcp.shared.session` (mit dem `RequestResponder`-Stub, den `message_handler`-Annotationen in v1 importierten) als Importpfade. (`mcp.types` ist *nicht* entfernt: Es bleibt als dauerhafter Alias für das eigenständige Paket `mcp_types`.)
* Die veraltete Schreibweise `streamablehttp_client` und der Callback `get_session_id` aus `streamable_http_client` (das jetzt genau zwei Streams liefert).
* `McpError`, umbenannt in **`MCPError`** mit einem direkten Konstruktor `(code, message, data)`.
* `MCPServer.get_context()`, `mount_path=` sowie die Dekorator-Methoden, die ContextVar und die Handler-Dicts des Low-Level-`Server`.

## Das Protokoll: von 2025-11-25 zu 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

v2 implementiert die Revision 2026-07-28, und es bedient **beide** Revisionen zugleich: Dieselbe `streamable_http_app()` (und derselbe stdio-Server) beantwortet das `initialize` eines Clients der 2025er-Generation und die Requests eines Clients der 2026er-Generation, ohne dass du etwas konfigurieren, ein Flag umlegen oder ein getrenntes Deployment aufsetzen musst. Die neue Revision zu bedienen lässt keinen Client auf der alten im Stich. Was folgt, ist das, was die neue Revision selbst ändert.

### Kein Handshake, keine Session {#no-handshake-no-session}

Ein 2026-07-28-Client öffnet nicht erst eine Verbindung, handelt aus und redet dann. Jeder Request trägt seine Protokollversion, die Client-Info und die Client-Capabilities in `_meta`, und der eine Discovery-Aufruf, `server/discover`, ist ein gewöhnlicher Request wie jeder andere. `Client` tut standardmäßig das Richtige: Er probiert `server/discover` einmal und fällt auf den `initialize`-Handshake zurück, wenn der Server älter ist.

Über Streamable HTTP gibt es auf dem 2026er-Pfad keine `Mcp-Session-Id`, und das ist die Schlagzeile für den Betrieb: **Nichts bindet einen modernen Request an einen Worker**, also kann jede Replik hinter einem schlichten Round-Robin-Load-Balancer ihn beantworten. Zwei ehrliche Einschränkungen. Deine Clients der 2025er-Generation (heute sind das die meisten Clients) öffnen weiterhin Sessions und brauchen weiterhin die Stickiness, die sie auf v1 brauchten; für sie ändert sich nichts. Und das Einzige, was der erneute Versuch eines *Multi-Roundtrips* über Worker hinweg mitnehmen muss, ist sein versiegelter `request_state`, dessen Standardschlüssel pro Prozess erzeugt wird, daher übergibt ein horizontal skaliertes Deployment `RequestStateSecurity(keys=[...])`. (`stateless_http=True` hat damit nichts zu tun: Es beeinflusst nur, wie Clients der 2025er-Generation bedient werden, und 2026er-Verkehr liest es nie; wenn du es in v1 bereits gesetzt hast, ändert sich nichts.)

**[Protokollversionen](protocol-versions.md)** ist die Client-Seite davon, **[Bereitstellen und skalieren](run/deploy.md)** die Checkliste für den Betrieb (die Host-Allowlist, der `request_state`-Schlüssel, Benachrichtigungen über Repliken hinweg), und **[Legacy-Clients unterstützen](run/legacy-clients.md)** erzählt, wie beide Generationen zugleich bedient werden.

### Der Server kann den Client nicht aufrufen: Multi-Roundtrip-Requests {#the-server-cannot-call-the-client-multi-round-trip-requests}

Jeder vom Server ausgehende Request ist bei 2026-07-28 entfernt: Push-Elicitation, Sampling, `roots/list`. Auf einer 2026er-Verbindung gibt es keinen Rückkanal (back-channel) dafür, also schlagen `ctx.elicit()` und `ctx.session.create_message()` dort mit `NoBackChannelError` fehl (für Legacy-Clients funktionieren sie weiterhin).

Der Ersatz dreht den Aufruf um. Ein Tool, das etwas von der Person am Host braucht, *gibt* die Frage *zurück* (`InputRequiredResult`), der Client beantwortet sie mit denselben Callbacks, die er schon immer hatte, und der Aufruf wird mit angehängten Antworten erneut versucht. `Client` treibt diese Schleife für dich. Auf dem Server baust du das Result selten selbst, weil eine **[Abhängigkeit](handlers/dependencies.md)** das übernimmt: Annotiere einen Parameter mit `Resolve(ask_quantity)`, wobei `ask_quantity` eine gewöhnliche Funktion ist, die du schreibst, und das SDK fragt über den Mechanismus, den die Verbindung unterstützt – ein Live-Elicitation-Request auf einer Legacy-Session oder ein Multi-Roundtrip bei 2026. Ein Tool-Body, beide Generationen:

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

Diese Datei ist das ganze Versprechen an einem Ort: ein Server, ein Tool mit `Resolve` dahinter, und ein Legacy-Client plus ein moderner Client, die beide ihre Antwort bekommen, im Speicher. **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)** erklärt den Mechanismus (einschließlich `request_state`, den das SDK für dich versiegelt und verifiziert); **[Elicitation](handlers/elicitation.md)** behandelt das Fragen.

!!! warning "Das ist die eine Stelle, an der ein portierter v1-Server sein Verhalten ändert"
    Deine eigenen Tests treffen es zuerst: `Client(mcp)` handelt gegen deinen v2-Server standardmäßig
    2026-07-28 aus, also schlägt ein Tool, das `ctx.elicit()` aufruft, in einem Test fehl, der auf v1 bestand.
    Verschiebe die Frage in einen `Resolve(...)`-Parameter (über Generationen portabel), oder pinne den
    Test-Client auf `mode="legacy"`, wenn du das Push-Verhalten wirklich willst.

### Roots, Sampling und Protokoll-Logging sind veraltet; `ping` ist entfernt {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) erklärt drei ganze *Capabilities* für veraltet, auf jeder Protokollversion: Roots, Sampling und Logging auf MCP-Ebene (`ctx.info()` und Verwandte). Das ist eine andere Achse als der fehlende Rückkanal oben; veraltet ist ein Hinweis, alles funktioniert gegen Sessions der 2025er-Generation weiter, und auf der Leitung ändert sich nichts. Was du bemerkst, ist `MCPDeprecationWarning`, eine `UserWarning`, die deshalb standardmäßig ausgegeben wird; rechne damit, dass dein erstes `ctx.info(...)` nach dem Upgrade das meldet.

Bei `ping` ist es strenger: aus dem Protokoll entfernt, nicht veraltet. Zwei eigenständige Methoden der veralteten Features sind bei 2026-07-28 auf dieselbe Weise entfernt, `logging/setLevel` und das `notifications/roots/list_changed` des Clients, und Fortschrittsbenachrichtigungen gehen jetzt nur noch vom Server zum Client.

**[Veraltete Features](deprecated.md)** hat die vollständige Tabelle, den Ersatz für jedes einzelne und den einzeiligen Filter, falls du ein ruhiges Log brauchst, während du Legacy-Clients bedienst.

### Änderungsbenachrichtigungen werden zu einem einzigen Stream {#change-notifications-become-one-stream}

Bei 2026-07-28 werden der eigenständige HTTP-GET-Stream und `resources/subscribe` durch `subscriptions/listen` ersetzt: Der Client öffnet einen langlebigen Stream und benennt die Arten von Benachrichtigungen, die er haben will. `MCPServer` bedient ihn ohne weitere Konfiguration; du veröffentlichst mit `await ctx.notify_resource_updated(uri)` (und `notify_tools_changed()` und so weiter), eine Middleware kann einen Listen-Request pro Aufrufer ablehnen, und Deployments mit mehreren Repliken binden einen gemeinsamen `SubscriptionBus` ein. Auf dem Client öffnet `async with client.listen(...)` den Stream: Der Filter geht als Schlüsselwortargumente hinein, typisierte Änderungsereignisse kommen zurück, und `sub.honored` ist die Teilmenge, die der Server zu liefern zugesagt hat.

**[Abonnements](handlers/subscriptions.md)** behandelt das Veröffentlichen und Bedienen, **[das Gegenstück unter Clients](client/subscriptions.md)** die beobachtende Seite und **[Bereitstellen und skalieren](run/deploy.md)** den Bus.

### Der Rest, in Kürze {#the-rest-quickly}

* **Identität ist optionale Metadaten pro Nachricht.** Der `_meta`-Schlüssel `clientInfo` auf der Request-Seite ist optional (das Pflichtpaar ist `protocolVersion` + `clientCapabilities`), und `serverInfo` ist aus dem Result-Body von `server/discover` ausgezogen: Server stempeln es stattdessen in das `_meta` jedes Results der 2026er-Generation ([Spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)). Das SDK stempelt immer; `client.server_info` ist `None`, wenn ein Server sich nicht zu erkennen gibt (zum Beispiel, weil eine Middleware den Schlüssel entfernt hat). **[Der Low-Level-Server](advanced/low-level-server.md)** zeigt den Stempel auf der Leitung.
* **Requests lassen sich routen, ohne Bodies zu parsen.** Moderne HTTP-Requests tragen `Mcp-Method` (und für die drei Tool-artigen Aufrufe `Mcp-Name`); eine Eigenschaft im Eingabeschema eines Tools, die mit `x-mcp-header` annotiert ist, wird in einen `Mcp-Param-*`-Header gespiegelt und vom Server gegengeprüft ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)). Gateways und Rate-Limiter können allein anhand der Header routen; die Regeln stehen im **[Migrationsleitfaden](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)**.
* **Results tragen Cache-Hinweise.** List- und Read-Results deklarieren `ttlMs` und `cacheScope` ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)); du setzt sie pro Methode mit `cache_hints=`, und `Client` beachtet sie mit einem eingebauten Response-Cache. Ein Server, der keine Hinweise sendet (jeder Server vor 2026), sieht identischen, ungecachten Verkehr. **[Caching-Hinweise](client/caching.md)**.
* **Erweiterungen sind vollwertig.** Server und Clients deklarieren optionale Capability-Bündel unter Reverse-DNS-Bezeichnern ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)); die eingebaute Erweiterung `Apps` (MCP Apps) ist die Referenz. **[Erweiterungen](advanced/extensions.md)** und **[MCP Apps](advanced/apps.md)**.
* **Fehlercodes wurden standardisiert.** Eine fehlende Ressource ist `-32602` mit dem URI in `error.data`, und die neuen von der Spezifikation reservierten Codes erscheinen als `-32020` (Header-Abweichung), `-32021` (fehlende erforderliche Capability) und `-32022` (nicht unterstützte Protokollversion). **[Fehlerbehebung](troubleshooting.md)** ist nach den exakten Meldungen geordnet.
* **Autorisierung lässt sich schwerer falsch benutzen.** Der Client validiert das `iss`, das mit dem Autorisierungscode zurückkommt ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207); dein `callback_handler` gibt jetzt ein `AuthorizationCodeResult` zurück), sendet `application_type` bei der Registrierung und spielt Zugangsdaten nie gegen einen anderen Autorisierungsserver erneut ab. Neu in der Enterprise-Ecke: der Identity-Assertion-Flow aus [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990). Der **[Migrationsleitfaden](migration.md)** listet jede OAuth-Änderung auf; die Seiten dazu sind **[OAuth für Clients](client/oauth-clients.md)** und **[Identity Assertion](client/identity-assertion.md)**.
* **Jeder Server ist nachverfolgbar.** OpenTelemetry ist als Middleware standardmäßig eingeschaltet: Jeder Request bekommt einen Server-Span, ohne Kosten, bis der Prozess einen Exporter konfiguriert. Wenn auf beiden Seiten das SDK läuft, propagiert der Client außerdem den W3C-Trace-Kontext in `_meta`, sodass die Traces zusammenfinden. **[OpenTelemetry](run/opentelemetry.md)**.

## Upgrade von v1? {#upgrading-from-v1}

* Der **[Migrationsleitfaden](migration.md)** ist die vollständige, exakte Liste dessen, was zu ändern ist; diese Seite war das Warum.
* **v1.x verschwindet nicht.** Es geht in die Wartung über, bekommt weiter kritische Fixes und Sicherheitspatches, und nichts an der Veröffentlichung der Spezifikation 2026-07-28 macht es kaputt; seine Doku liegt unter [/v1/](https://py.sdk.modelcontextprotocol.io/v1/). Wenn du eine Bibliothek veröffentlichst, die von `mcp` abhängt, und noch nicht zur Migration bereit bist, setze eine Obergrenze (zum Beispiel `mcp>=1.28,<2`), damit eine ungepinnte Auflösung auf 1.x bleibt.
* Etwas holprig, verwirrend oder kaputt? **[Gib v2-Feedback](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**; alles wird gelesen.
