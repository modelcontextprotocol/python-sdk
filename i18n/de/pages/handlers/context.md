---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Der Context {#the-context}

Die Argumente eines Tools kommen vom Modell. Alles andere (der Request, den du gerade bearbeitest, der Server, in dem du lebst, ein Weg zurück zum Client) kommt aus einem einzigen Objekt: dem **`Context`**.

Du erzeugst ihn nicht selbst und konfigurierst ihn auch nicht. Du forderst ihn einfach an.

## Anfordern {#ask-for-it}

Füge einem beliebigen Tool einen Parameter hinzu, der mit `Context` annotiert ist:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* Das SDK baut für jeden Request einen frischen `Context` und übergibt ihn.
* Der **Name des Parameters spielt keine Rolle**. `ctx`, `context`, `c`: Das SDK findet ihn über seine Annotation.
* Ressourcen und Prompts können ebenfalls einen deklarieren, auf dieselbe Weise.
* `ctx.request_id` ist die ID des Requests, den deine Funktion gerade bearbeitet.

!!! info
    Wenn du FastAPI kennst, kennst du diesen Kniff: Deklariere einen Parameter mit dem
    frameworkeigenen Typ (`Request` dort, `Context` hier), und das Framework liefert ihn. Nichts zu
    registrieren, nichts zu konfigurieren: Die Typannotation ist der ganze Mechanismus.

### Für das Modell unsichtbar {#invisible-to-the-model}

Das ist der Teil, den du verinnerlichen solltest. Hier ist das Eingabeschema, das `tools/list` für `search_books` meldet:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

Eine Eigenschaft. `ctx` ist kein Argument: Es taucht nie im Schema auf, das Modell erfährt nie davon, und kein Client kann es ausfüllen. Es ist ein Vertrag zwischen dir und dem SDK, unsichtbar auf der Leitung.

### Ausprobieren {#try-it}

Starte den Server mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Das Formular für `search_books` hat ein einziges Feld `query`. Rufe es mit `dune` auf:

```text
[request 3] Found 3 books matching 'dune'.
```

Die Zahl ist die Nummer des Requests, der es zufällig war. Rufe das Tool noch einmal auf, und sie ändert sich: Jeder Request bekommt seinen eigenen `Context`.

## Was er dir bietet {#what-it-gives-you}

Das injizierte Objekt ist klein. Neben `request_id`:

* `await ctx.read_resource(uri)`: eine der **eigenen** Ressourcen des Servers aus einem Tool heraus lesen. Der nächste Abschnitt.
* `await ctx.report_progress(progress, total, message)`: während eines langen Aufrufs Fortschritt an den Aufrufer zurückstreamen. Alles Weitere steht in **[Fortschritt](progress.md)**.
* `await ctx.elicit(message, schema)` und `await ctx.elicit_url(...)`: das Tool anhalten und der Person am Host eine Frage stellen. Das ist **[Elicitation](elicitation.md)** (Rückfrage bei der Person am Host).
* `ctx.session`: die Server-Seite des Gesprächs mit diesem Client. Benachrichtigungen, die du an den Client schickst, leben hier; der letzte Abschnitt nutzt sie.
* `ctx.headers`: die Request-Header, die der Transport mitgebracht hat, oder `None` bei stdio. Einen eigenen Header liest du mit `(ctx.headers or {}).get("x-...")`. Header sind vom Client gelieferte Eingaben – in Ordnung für eine Locale oder ein Feature-Flag, nie für eine Identität.
* `ctx.request_context`: der rohe Datensatz pro Request. Das Feld, nach dem du greifen wirst, ist `lifespan_context`, das Objekt, das dein Startcode per yield geliefert hat (siehe **[Lifespan](lifespan.md)**).

Logging steht bewusst nicht auf dieser Liste. Ein Server loggt mit Pythons Modul `logging`, wie jedes andere Python-Programm. **[Logging](logging.md)** ist die kurze Seite, die erklärt, warum.

!!! tip
    Injiziert wird nur in die Funktion, die du registriert hast. Eine Hilfsfunktion, die dein Tool
    aufruft, bekommt keinen eigenen `Context`; reiche `ctx` als gewöhnliches Argument weiter. Es gibt
    keinen umgebenden „aktuellen Kontext“, den du von woanders holen könntest.

## Eigene Ressourcen lesen {#read-your-own-resources}

Die Ressourcen eines Servers sind nicht nur für Clients da. Auch ein Tool kann sie lesen:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` löst den URI über dieselbe Registry auf, die auch `resources/read` bedient. Ein Tool bekommt also, was ein Client bekäme: ein Iterable von `ReadResourceContents`, eines pro Content-Block. Für diesen URI gibt es einen:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` ist genau das, was `genres()` zurückgegeben hat. Eine einzige Quelle der Wahrheit: Der Client durchstöbert die Ressource, deine Tools konsumieren sie, niemand kopiert den String.
* Der einzige Parameter von `describe_catalog` ist der `Context`, daher hat sein Eingabeschema **überhaupt keine Eigenschaften**. Das Modell ruft es mit `{}` auf.

## Dem Client mitteilen, dass sich die Liste geändert hat {#tell-the-client-the-list-changed}

Was ein Server anbietet, steht nicht zur Importzeit fest. Registriere ein Tool zur Laufzeit und teile es dann dem Client mit:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` registriert eine gewöhnliche Funktion als Tool: Name, Beschreibung und Schema werden genau so abgeleitet, wie `@mcp.tool()` es getan hätte.
* `await ctx.session.send_tool_list_changed()` sendet `notifications/tools/list_changed`. Ein Client, der das empfängt, ruft `tools/list` erneut auf und sieht `recommend_book`.

Die Geschwister sind `send_resource_list_changed()`, `send_prompt_list_changed()` und `send_resource_updated(uri)` für eine Änderung an einer bestimmten Ressource.

Auf einer Verbindung mit 2026-07-28 empfangen Clients Änderungsbenachrichtigungen nur auf einem `subscriptions/listen`-Stream, den sie selbst geöffnet haben. Die `send_*`-Methoden oben erreichen diese Streams daher nicht. Die Publish-Methoden des `Context` liefern an alle abonnierten Streams gleichzeitig aus: `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()` und `await ctx.notify_resource_updated(uri)`. Alles Weitere, einschließlich der horizontalen Skalierung über Replikate, steht in **[Abonnements](subscriptions.md)**.

!!! check
    Bevor jemand `enable_recommendations` ausführt, existiert das Tool, das du versprichst, nicht.
    Rufst du es trotzdem auf, ist das Ergebnis ein Fehler, den das Modell lesen kann:

    ```text
    Unknown tool: recommend_book
    ```

    Führe `enable_recommendations` aus, und genau derselbe Aufruf gelingt. Die Tool-Liste ist
    wirklich dynamisch: `tools/list` spiegelt wider, was *gerade jetzt* registriert ist.

## Zusammenfassung {#recap}

* Annotiere einen Parameter mit `Context` (in einem Tool, einer Ressource oder einem Prompt), und das SDK injiziert ihn. Der Name gehört dir.
* Er ist für das Modell unsichtbar: Das Eingabeschema enthält immer nur deine echten Argumente.
* `ctx.request_id` identifiziert den Request; `ctx.request_context.lifespan_context` ist das, was dein Startcode per yield geliefert hat.
* Mit `await ctx.read_resource(uri)` liest ein Tool die eigenen Ressourcen des Servers.
* `ctx.session` ist der Kanal zurück zum Client: `send_tool_list_changed()` und seine Geschwister sagen ihm, dass er eine Liste, die du geändert hast, erneut abrufen soll.
* Auch Fortschrittsmeldungen und Elicitation beginnen beim `Context`; beide haben ihre eigene Seite.

Parameter, die das Modell nie sieht und die deine eigenen Funktionen füllen, sind **[Abhängigkeiten](dependencies.md)**.
