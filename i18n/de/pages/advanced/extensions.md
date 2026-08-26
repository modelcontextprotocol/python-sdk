---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# Extensions {#extensions}

Eine **Extension** ist ein optionales Bündel von MCP-Verhalten hinter einem einzigen Identifier.

Auf einem Server kann sie Tools, Ressourcen und neue Request-Methoden beisteuern, und sie kann `tools/call` umhüllen. Auf einem Client kann sie zusätzliche Ergebnisformen von `tools/call` für sich beanspruchen und Vendor-Benachrichtigungen beobachten. Jede Seite kündigt sie unter ihrem eigenen `capabilities.extensions` an, und für alle, die nicht darum gebeten haben, ändert sich nichts. Das ist der Vertrag ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)), und er hat eine goldene Regel: **Extensions sind standardmäßig aus**.

## Eine Extension verwenden {#using-an-extension}

Übergib Instanzen bei der Konstruktion:

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

Fertig. Der Server kündigt jetzt `io.modelcontextprotocol/ui` unter `capabilities.extensions` an und bedient alles, was die Extension beisteuert.

`Apps` ist die eingebaute Referenz-Extension und bekommt eine eigene Seite: **[MCP Apps](apps.md)**.

!!! note
    Extensions stehen bei der Konstruktion fest. Es gibt kein `add_extension`, das du später aufrufen könntest: Die Capability-Map eines Servers sollte sich nicht ändern, während Clients mit ihm verbunden sind.

Die Capability-Map reist mit `server/discover`, und das ist ein Pfad von **2026-07-28**. Ein Legacy-`initialize`-Handshake hat keinen Platz dafür, also sieht ein Legacy-Client die Extension schlicht nicht. Plane das ein: Eine Extension *ergänzt* einen Server, sie darf nicht der einzige Weg sein, auf dem der Server nutzbar ist.

## Eine eigene Extension schreiben {#writing-your-own}

Leite von `Extension` ab und überschreibe nur, was du brauchst. Jede Methode hat eine Standardimplementierung.

### Der Identifier {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

Der Identifier ist ein `vendor-prefix/name`-String nach der `_meta`-Schlüsselgrammatik der Spezifikation: durch Punkte getrennte Labels (jedes beginnt mit einem Buchstaben und endet mit einem Buchstaben oder einer Ziffer), ein Schrägstrich, dann der Name. Er wird **bei der Definition der Klasse** validiert, ein Tippfehler wartet also nicht darauf, dass ein Server startet:

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

Nimm als Präfix eine Domain, die du kontrollierst. `io.modelcontextprotocol/*` ist Extensions vorbehalten, die das MCP-Projekt selbst spezifiziert.

### Tools beisteuern {#contributing-tools}

Die kleinste nützliche Extension besteht aus einem Tool und einer Settings-Map:

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` gibt `ToolBinding`s zurück. Der Server registriert jedes einzelne genau so, als hättest du selbst `mcp.add_tool(...)` aufgerufen: dieselbe Schema-Generierung, dieselbe `Context`-Injection, alles gleich.
* `settings()` ist der Wert, der unter `capabilities.extensions["com.example/stamps"]` angekündigt wird. Gib `{}` zurück (den Standardwert), um die Extension ohne Settings anzukündigen.
* Die Extension bekommt den Server nie in die Hand. Sie deklariert ihre Beiträge als Daten; `MCPServer` verarbeitet sie. Es gibt kein `self.server`, das sie verändern könnte.

Und `main()` ist der Beweis, ein In-Memory-Client direkt gegen `mcp`:

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### Eigene Methoden bedienen {#serving-your-own-methods}

Eine Extension kann **neue Request-Methoden** registrieren: eigene Verben, bedient neben denen der Spezifikation:

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` leitet von `RequestParams` ab, sodass der `_meta`-Umschlag von 2026 einheitlich geparst wird und dein Handler validierte Parameter bekommt, nie ein rohes Dict. Begrenze, was der Client kontrolliert: `Field(ge=1, le=100)` weist ein absurdes `limit` zurück, bevor dein Code irgendetwas dafür alloziert.
* `require_client_extension(ctx, EXTENSION_ID)` ist die Schranke: Ein Client, der die Extension nicht deklariert hat, bekommt den Fehler `-32021` (missing required client capability), samt der maschinenlesbaren `requiredCapabilities`-Payload, die die Spezifikation verlangt.
* `protocol_versions=frozenset({"2026-07-28"})` heftet die Methode an genau eine Protokollversion auf der Leitung. Bei jeder anderen Version bekommt der Client `METHOD_NOT_FOUND`, genau so, als gäbe es die Methode dort nicht. Für diesen Client gibt es sie auch nicht.

Methoden sind **strikt additiv**. Das SDK erzwingt das bei der Konstruktion, nicht zur Laufzeit:

* Ein `MethodBinding` für eine in der Spezifikation definierte Methode (`tools/list`, `completion/complete`, ...) löst `ValueError` aus, wenn das Binding konstruiert wird. Kernverben gehören dem Server.
* Zwei Extensions, die dieselbe Methode binden, lösen eine Exception aus, sobald sich die zweite registriert. Last-write-wins ist genau der Weg, auf dem Plugins einander beschädigen; das machen wir nicht.
* Ein leeres `protocol_versions`-Set löst ebenfalls eine Exception aus: Eine Methode, die nie bedient werden kann, ist ein Bug, keine Konfiguration.

### Die Client-Seite {#the-client-side}

Das `main()` derselben Datei ist die ganze Client-Geschichte, beide Hälften davon:

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` deklariert die Extension. Die Deklarationen werden zu `ClientCapabilities.extensions`: Auf einer 2026-07-28-Verbindung reist die Map im `_meta`-Umschlag jedes einzelnen Requests, der Server sieht sie also bei **jedem** Request; auf einer Legacy-Verbindung reist sie mit dem `initialize`-Handshake. Dem Server-Code ist das egal: `require_client_extension(ctx, ...)` und `ctx.session.check_client_capability(...)` lesen auf beiden Pfaden die richtige Quelle.
* Vendor-Methoden steigen eine Schicht tiefer zu `client.session.send_request(...)` hinab; `Client` bekommt nur für Verben der Spezifikation eigene Methoden. `send_request` akzeptiert jede `Request`-Unterklasse, der Vendor-Request geht also unverändert durch.

### `tools/call` abfangen {#intercepting-toolscall}

Der eine eingreifende Hook. Überschreibe `intercept_tool_call`, um einen Tool-Aufruf zu beobachten, kurzzuschließen oder zu verhindern:

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` sind die validierten `CallToolRequestParams`: Du bekommst `params.name` und `params.arguments`, ohne rohes JSON anzufassen. Sie entscheiden auch, welcher Tool-Aufruf läuft: Reichst du über `call_next` einen umgeschriebenen Kontext weiter, ändert das, was der Handler auf `ctx` sieht, nicht den Tool-Aufruf selbst. Das Umschreiben von Requests auf Leitungsebene gehört in die [Middleware](middleware.md).
* `call_next(ctx)` führt den Rest der Kette aus und gibt das Ergebnis des Handlers zurück. Gib es unverändert zurück (beobachten), gib etwas anderes zurück (ersetzen) oder löse einen `MCPError` aus (ablehnen). Was immer du zurückgibst, wird wie jedes Handler-Ergebnis serialisiert, einschließlich des `serverInfo`-Identitätsstempels der 2026er-Generation, ein kurzschließender Interceptor erzeugt also nie eine anonyme oder vom Schema abweichende Response.
* Bei mehreren Extensions schachteln sich die Interceptors in Registrierungsreihenfolge: Die erste Extension in `extensions=[...]` liegt ganz außen.
* Die Standardimplementierung reicht einfach durch, und ein Server, dessen Extensions diesen Hook nie überschreiben, behält den nackten `tools/call`-Handler unangetastet. Du zahlst nicht für das, was du nicht nutzt.

Der Hook umhüllt `tools/call` und sonst nichts. Für alles, was jede Nachricht betrifft, nimm [Middleware](middleware.md). Dafür ist sie da.

## Eine Client-Extension verwenden {#using-a-client-extension}

Eine **Client-Extension** ist derselbe Vertrag von der konsumierenden Seite: ein Bündel clientseitigen Verhaltens hinter einem einzigen Identifier. Übergib Instanzen an `Client(extensions=[...])` und rufe Tools ganz normal auf:

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` gibt ein gewöhnliches `CallToolResult` zurück, wie jeder andere Aufruf. Was die Extension geändert hat: Der Server darf `buy` jetzt mit einer `receipt`-**Ergebnisform** statt mit einem endgültigen Ergebnis beantworten, und `Receipts` bringt sie zu Ende (hier, indem sie den Beleg mit einem Folgeaufruf einlöst), bevor `call_tool` zurückkehrt. An der Aufrufstelle bewegt sich nichts.

Lass die Extension weg, und nichts davon existiert: Die Schranke des Servers weist einen Client ab, der sie nicht deklariert hat (Fehler -32021), und eine beanspruchte Form von einem Server, der die Schranke überspringt, fällt durch die Validierung, genau wie die Spezifikation es für einen unbekannten `resultType` verlangt. Standardmäßig aus, an beiden Enden der Leitung.

Um einen Identifier **ohne** clientseitiges Verhalten anzukündigen (der Server prüft die Capability, der Client tut nichts, wie beim Search-Client oben), nimm `advertise()`:

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## Eine Client-Extension schreiben {#writing-a-client-extension}

Leite von `ClientExtension` ab und überschreibe nur, was du brauchst. Drei Arten von Beiträgen, jede mit einer Standardimplementierung: `settings()`, `claims()` und `notifications()`.

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* Der Identifier folgt derselben Grammatik wie auf dem Server und wird validiert, wenn die Klasse definiert wird.
* `claims()` gibt `ResultClaim`s zurück: ein Tag auf der Leitung, das Model, das es parst, und der Resolver, der es zu Ende bringt. Das Model muss das Tag mit `result_type: Literal["receipt"]` festlegen und darf nicht von den Kern-Ergebnistypen des Verbs ableiten; beides wird erzwungen, wenn der Claim konstruiert wird. Vendor-Felder wie `receipt_token` gehen unverändert über die Leitung: Eine ersetzte Form erreicht den Client wortwörtlich.
* Der Resolver erhält das geparste Model und einen `ClaimContext`; `ctx.session` ist derselbe öffentliche Griff wie `client.session`, Folgeaufrufe sind also gewöhnliche Session-Aufrufe. Er gibt das normale `CallToolResult` des Verbs zurück.
* `settings()` ist der Wert, der unter `ClientCapabilities.extensions[identifier]` angekündigt wird, einmal bei der Konstruktion von `Client` gelesen.

`notifications()` deklariert Vendor-Benachrichtigungen des Servers, die beobachtet werden sollen:

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

Der Handler erhält validierte Parameter, eine Benachrichtigung nach der anderen, in Dispatch-Reihenfolge. Er beobachtet; ein Veto einlegen oder antworten kann er nicht.

Zwei stille Regeln. Claims sind nur auf 2026-07-28-Verbindungen aktiv, und die Capability-Ankündigung folgt ihnen: Auf einer Legacy-Verbindung lösen sich die Claims auf, und der Identifier fällt mit ihnen aus der Ankündigung heraus, der Client kündigt also nie eine Extension an, deren Formen er zurückweisen würde. Und wenn du die beanspruchte Form selbst statt des Resolvers haben willst, rufe `client.session.call_tool(..., allow_claimed=True)` auf; ohne dieses Flag löst eine beanspruchte Form, die bei einem Aufrufer auf Session-Ebene ankommt, `UnexpectedClaimedResult` aus.

### Extension-Verben {#extension-verbs}

Die eigenen Request-Methoden einer Extension brauchen keine clientseitige Registrierung. Ein Vendor-Request-Typ leitet von `mcp.types.Request` ab und geht durch `client.session.send_request`, wie in [Eigene Methoden bedienen](#serving-your-own-methods). Eine Ergänzung: Wenn ein Params-Schlüssel im `Mcp-Name`-Header mitreisen muss (Extension-Spezifikationen wie Tasks verlangen das für ihre Verben), deklariert der Request-Typ `name_param`:

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

Die Session spiegelt `params["jobId"]` auf jedem Sendepfad in `Mcp-Name`, und ein fehlender Wert scheitert laut, statt einen erforderlichen Header stillschweigend wegzulassen.

## Was eine Extension nicht kann {#what-an-extension-cannot-do}

Die Fläche für Beiträge ist absichtlich **geschlossen**. Auf dem Server: Settings, Tools, Ressourcen, Methoden, ein `tools/call`-Interceptor. Auf dem Client: Settings, Result-Claims, Notification-Bindings. Eine Extension kann nicht:

* **In den Host hineingreifen.** Sie deklariert Daten; sie hält keine Referenz auf Server oder Client.
* **Kernverhalten ersetzen.** Methoden der Spezifikation und Kern-Ergebnistags werden bei der Konstruktion abgewiesen (`initialize` reserviert der Runner von vornherein für sich); ein Notification-Binding, das vom Kernvokabular überdeckt wird, verstummt stattdessen mit einer Warnung.
* **Sich nachträglich registrieren.** Sobald `MCPServer(...)` oder `Client(...)` zurückgekehrt ist, ist die Menge der Extensions, wie sie ist.

Wenn du gegen diese Wände ankämpfst, schreibst du keine Extension. Du schreibst einen Fork. Die Wände sind das Feature: Wer `extensions=[Apps(), Stamps()]` liest, weiß *alles*, was diese beiden angefasst haben können.
