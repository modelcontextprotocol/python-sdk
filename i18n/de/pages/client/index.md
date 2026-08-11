---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# Der Client {#the-client}

Ein **`Client`** ist der Weg, auf dem ein Python-Programm mit einem MCP-Server spricht.

Er ist ein einziges Objekt mit einem einzigen Lebenszyklus: erzeugen, `async with` betreten, Methoden aufrufen. Jedes Verb des Protokolls (die Tools auflisten, eines aufrufen, eine Ressource lesen, einen Prompt rendern) ist eine `async`-Methode darauf, die ein typisiertes Ergebnis zurückgibt.

## Der erste Client {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

Der Server oben ist nur da, damit du etwas hast, womit du dich verbinden kannst. Der Client sind die fünf hervorgehobenen Zeilen.

* `Client(mcp)` bekommt das **Server-Objekt selbst**. Das ist der In-Memory-Transport: kein Subprozess, kein Port, kein HTTP. So verbindet sich jedes Beispiel auf dieser Seite und jeder Test, den du schreibst.
* `async with` ist der **Lebenszyklus**. Beim Betreten wird verbunden und ausgehandelt, beim Verlassen getrennt. Es gibt kein `connect()`/`close()`-Paar, und ein `Client` lässt sich nach dem Ende des Blocks nicht wiederverwenden.
* Innerhalb des Blocks liegen die Fakten zur Verbindung bereits als einfache Properties vor.

### Was sich an `Client` übergeben lässt {#what-you-can-pass-to-client}

`Client` nimmt ein positionelles Argument und leitet den Transport aus dessen Typ ab:

* Eine Instanz von `MCPServer` (oder des Low-Level-`Server`): Verbindung **im selben Prozess**.
* Ein URL-String (`Client("http://localhost:8000/mcp")`): Streamable HTTP, der Weg für die Produktion.
* Ein **Transport**: alles, was sich mit `async with ... as (read, write)` verwenden lässt, etwa `stdio_client(...)` um einen Subprozess herum.

Alles Übrige auf dieser Seite ist in allen drei Fällen identisch. Header, Subprozesse, Timeouts und das `Transport`-Protokoll haben ihre eigene Seite: **[Client-Transporte](transports.md)**.

### Was ein verbundener Client mitbringt {#whats-on-a-connected-client}

Vier schreibgeschützte Properties, die gefüllt sind, sobald du den Block betrittst:

* `client.server_info`: die Identität des Servers oder `None` bei einem Server der 2026er-Generation, der keine meldet (python-sdk-Server tun das standardmäßig). `server_info.name` ist hier `"Bookshop"`, `server_info.version` ist das, was der Server meldet.
* `client.server_capabilities`: was der Server kann (`tools`, `resources`, `prompts`, `completions`, ...). Eine Capability, die der Server nicht hat, ist `None`.
* `client.protocol_version`: die Protokollversion, auf die sich beide Seiten geeinigt haben. Hier ist sie `"2026-07-28"`.
* `client.instructions`: der `instructions=`-String des Servers oder `None`, wenn er keinen gesetzt hat.

Eine Protokollversion hast du nie ausgewählt. Standardmäßig sondiert der `Client` den Server und fällt bei älteren auf den klassischen Handshake zurück, sodass ein einziger Client mit Servern jeder Generation funktioniert. Wenn du das steuern musst: Alles Weitere steht in **[Protokollversionen](../protocol-versions.md)**.

!!! tip
    `client.session` ist die darunterliegende `ClientSession`, der Low-Level-Notausgang.
    Für nichts auf dieser Seite wirst du sie brauchen.

## Tools auflisten {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` gibt ein `ListToolsResult` zurück; die Tools stehen in `.tools`. Jedes davon ist die vollständige Definition, die ein Host einem Modell übergeben würde:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

und `tool.input_schema` ist das JSON-Schema, das der Server aus den Type Hints der Funktion abgeleitet hat:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Dieses Schema ist alles, was eine UI braucht, um ein Argumentformular zu rendern, und alles, was ein Modell braucht, um gültige Argumente zu erzeugen.

!!! tip
    `title` ist optional, also muss sich eine UI, die einem Menschen Tools anzeigt, entscheiden: den `title`, wenn es einen gibt,
    sonst den `name`. `from mcp.shared.metadata_utils import get_display_name` macht genau das –
    für Tools, Ressourcen, Ressourcen-Templates und Prompts.

## Ein Tool aufrufen {#calling-a-tool}

`call_tool(name, arguments)` führt das Tool aus und gibt dir ein `CallToolResult` zurück.

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

`lookup_book` auf dem Server gibt ein Pydantic-`Book` zurück. Das sieht der Client:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

Ein Rückgabewert, drei Dinge zu lesen. Jedes hat einen anderen Abnehmer.

### `content`: was das Modell liest {#content-what-the-model-reads}

`content` ist eine `list` von **Content-Blöcken**, und ein Content-Block ist eine Union: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink` oder `EmbeddedResource`. Ein Tool kann mehrere zurückgeben, auch verschiedener Art.

Deshalb grenzt `main` mit `isinstance(block, TextContent)` ein, bevor es `block.text` anfasst. Beachte, dass es kein `.text` außerhalb des `isinstance` gibt: Der Typprüfer lässt das nicht zu, denn `ImageContent` hat `.data`, nicht `.text`. Die Union ist ehrlich darüber, was ein Tool dir schicken darf; dein Code sollte es auch sein.

### `structured_content`: was deine Anwendung liest {#structured_content-what-your-application-reads}

`structured_content` ist der Rückgabewert des Tools als JSON, passend zum deklarierten `output_schema` des Tools. Kein String-Parsing, kein Raten.

Wenn beide vorhanden sind, sagen sie absichtlich zweimal dasselbe: `content` ist für ein Modell, `structured_content` ist für Code. Woher die strukturierte Hälfte kommt und wie du sie steuerst, steht auf der Seite **[Strukturierte Ausgabe](../servers/structured-output.md)**.

### `is_error`: ob das Tool fehlgeschlagen ist {#is_error-whether-the-tool-failed}

Ein Tool, das eine Exception auslöst, löst in deinem Client **keine** aus. Es kommt als gewöhnliches Ergebnis mit `is_error=True` zurück.

!!! check
    Frag `lookup_book` nach `"Solaris"` (einem Titel, der nicht im Katalog steht), und die Funktion löst
    `ValueError` aus. Der Aufruf kehrt trotzdem normal zurück:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    Die Meldung der Exception ist in `content` gelandet, wo das **Modell** sie lesen und es erneut versuchen kann. Das
    ist Absicht: Ein Tool-Fehler ist Teil des Gesprächs, kein Absturz. Sieh dir immer `is_error` an,
    bevor du `structured_content` vertraust.

!!! warning
    `is_error=True` deckt mehr ab als dein eigenes `raise`. Frag nach einem Tool, das der Server gar nicht hat
    (`call_tool("does_not_exist", {})`), und nichts wird ausgelöst. Du bekommst dieselbe Form zurück,
    `is_error=True` mit `Unknown tool: does_not_exist` in `content`. Eine `Client`-Methode löst
    `MCPError` nur aus, wenn der Server mit einem JSON-RPC-**Fehler** statt eines Ergebnisses antwortet, und
    **[Fehler behandeln](../servers/handling-errors.md)** erklärt, wann ein Server welches davon erzeugt.

## Ressourcen {#resources}

Die Ressourcen-Verben kommen paarweise: zwei Wege zum Auflisten, einer zum Lesen.

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` gibt die **konkreten** Ressourcen zurück, die mit festem URI. Hier: `['catalog://genres']`.
* `list_resource_templates()` gibt die **parametrisierten** zurück. Hier: `['catalog://genres/{genre}']`. Es sind zwei verschiedene Listen, weil ein Template erst lesbar ist, wenn du es ausfüllst.
* `read_resource(uri)` nimmt einen URI als einfachen `str` und funktioniert mit beiden: Übergib `"catalog://genres/poetry"`, und der Server ordnet ihn dem Template zu.

`read_resource` gibt `contents` zurück, eine Liste aus `TextResourceContents` oder `BlobResourceContents`. Dieselbe Idee wie beim Tool-Content: mit `isinstance` eingrenzen, dann `.text` (oder `.blob`) lesen.

Ein Client kann sich auch mitteilen lassen, wann sich eine Ressource ändert. Auf Verbindungen der 2025er-Generation geschieht das über `subscribe_resource(uri)` / `unsubscribe_resource(uri)` – ein Methodenpaar, das `MCPServer` nicht implementiert, sodass der Request auf der 2026-07-28-Leitung (wo es diese Verben nicht mehr gibt) mit `-32601`, *Method not found*, beantwortet wird. Der Ersatz in 2026 ist ein `subscriptions/listen`-Stream, den `MCPServer` *sehr wohl* bedient – `server_capabilities.resources.subscribe` ist dort `True` –, und wie du ihn mit `client.listen(...)` konsumierst, steht auf der Seite **[Abonnements](subscriptions.md)** in diesem Abschnitt.

## Prompts {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` sagt dir, was der Server anbietet und was jeder Prompt braucht:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` rendert ihn. Das Argument-Dict ist `str -> str`: Prompt-Argumente sind immer Strings. Das Ergebnis ist `messages`, eine Liste von `PromptMessage`, jeweils mit einer `role` und einem `content`-Block:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

Ein Host reicht diese Nachrichten direkt an das Modell weiter. Das ist das ganze Feature.

## Vervollständigungen {#completions}

Ein Server mit einem Handler für Vervollständigungen kann Argumente von Prompts und Ressourcen-Templates automatisch vervollständigen, während die Person tippt.

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` sagt, *welchen* Prompt oder welches Template du ausfüllst: eine `PromptReference` oder eine `ResourceTemplateReference`.
* `argument` ist `{"name": ..., "value": ...}`: das Argument und das, was die Person bisher getippt hat.

Die Antwort steht in `result.completion.values`. Tippe `"p"`, und der Server liefert `['poetry']`. Die Serverseite, und wie ein Handler die *anderen*, bereits ausgefüllten Argumente nutzt, um seine Vorschläge einzugrenzen, steht auf der Seite **[Vervollständigungen](../servers/completions.md)**.

## Paginierung {#pagination}

Jede `list_*`-Methode nimmt ein Keyword-Argument `cursor=`, und jedes Ergebnis trägt einen `next_cursor`. Wenn `next_cursor` `None` ist, hast du alles.

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

Diese Schleife ist gegenüber jedem Server korrekt. `MCPServer` gibt alles auf einer Seite zurück, also ist `next_cursor` `None` und die Schleife läuft einmal – deshalb schreibt der meiste Code sie nie. Server, die wirklich paginieren, und die Regeln, denen Cursor gehorchen, stehen in **[Paginierung](../advanced/pagination.md)**.

## In Tests {#in-tests}

`Client(mcp)` ohne Prozess und ohne Port ist bereits ein Test-Harness für deinen Server.

Dafür gibt es ein eigenes Konstruktor-Flag: `Client(mcp, raise_exceptions=True)`. Es wirkt nur auf In-Memory-Verbindungen, und **[Testen](../get-started/testing.md)** ist die Seite, die es erklärt und das ganze Muster darum herum aufbaut.

## Zusammenfassung {#recap}

* `Client(x)` verbindet sich in-memory mit einem Server-Objekt, über Streamable HTTP mit einem URL-String und über alles andere per Transport.
* `async with` ist der ganze Lebenszyklus. Darin sind `server_capabilities` und `protocol_version` bereits gefüllt; `server_info` und `instructions` ebenfalls, wenn der Server sie liefert.
* `list_tools()` gibt dir für jedes Tool `name`, `title`, `description` und `input_schema`.
* `call_tool()` gibt `content` für das Modell, `structured_content` für deinen Code und `is_error` zurück. Ein Tool, das eine Exception auslöst, ist ein Ergebnis, keine Exception.
* `content` ist eine Union von Blocktypen; grenze mit `isinstance` ein, bevor du liest.
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt` und `complete` runden die Verben ab.
* Jede `list_*`-Methode nimmt `cursor=`; iteriere, bis `next_cursor` `None` ist.

Was ein Server vom *Client* anfordern kann und wie du darauf antwortest, steht in **[Client-Callbacks](callbacks.md)**.
