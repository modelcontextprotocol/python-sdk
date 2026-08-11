---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# Tools {#tools}

Ein **Tool** ist eine Funktion, die das Modell aufrufen kann.

Du deklarierst eines, indem du `@mcp.tool()` auf eine ganz normale Python-Funktion setzt. Das ist die ganze API.

## Dein erstes Tool {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

Sieh dir an, was du geschrieben hast. Keine Schemas, kein JSON, kein Protokoll, nur eine Funktion. Das SDK liest drei Dinge daraus:

* Der **Name** des Tools ist der Name der Funktion: `search_books`.
* Die **Beschreibung**, die das Modell sieht, ist der Docstring: `Search the catalog by title or author.`
* Die **Argumente**, die das Modell übergeben darf, ergeben sich aus den Type Hints: `query: str` und `limit: int`.

### Das Eingabeschema {#the-input-schema}

Aus diesen Type Hints erzeugt das SDK ein JSON Schema und sendet es während `tools/list` an den Client:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

Beide Argumente stehen in `required`, weil keines einen Standardwert hat. Das änderst du gleich. (Die `title`-Schlüssel sind Pydantic-Artefakte; die Properties, ihre Typen und `required` sind der Vertrag.)

!!! tip
    Type Hints sind hier keine Dokumentation. Sie sind **der Vertrag**. Sendet ein Client `"limit": "ten"`,
    weist das SDK das zurück, bevor deine Funktion überhaupt läuft.

### Was das Modell zurückbekommt {#what-the-model-gets-back}

Ruf das Tool mit `{"query": "dune", "limit": 5}` auf, und das Ergebnis hat zwei Teile:

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` ist der Text, den das **Modell** liest. `structured_content` sind typisierte Daten für die **Client-Anwendung**. Es ist da, weil du den Rückgabetyp als `-> str` deklariert hast.

Kümmere dich noch nicht um `structured_content`. Gib aus deinen Tools echte Python-Objekte zurück, und es passiert das Richtige; die Seite **[Strukturierte Ausgabe](structured-output.md)** dreht sich genau darum.

### Ausprobieren {#try-it}

Starte den Server mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Öffne die URL, die er ausgibt, geh zum Tab **Tools** und ruf `search_books` auf.

Der Inspector zeigt ein Formular mit einem erforderlichen Textfeld `query` und einem erforderlichen Zahlenfeld `limit`. Dieses Formular hat er aus deinen Type Hints gebaut. Das macht jeder andere MCP-Client genauso.

## Optionale Argumente {#optional-arguments}

Gib einem Parameter einen Standardwert, und er ist nicht mehr erforderlich. Das ist alles. Ganz normales Python.

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

Das Schema zieht mit:

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

`limit` ist aus `required` verschwunden und hat `"default": 10` bekommen. Ein Client, der es weglässt, bekommt `10` – genau wie in Python.

## Reichere Schemas mit `Field` {#richer-schemas-with-field}

Type Hints bringen dich weit, aber manchmal willst du ein Argument *beschreiben* oder einschränken.

Verpacke den Typ in `Annotated` und füge ein Pydantic-`Field` hinzu:

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

Drei neue Dinge, alle an den Parametern:

* `Field(description=...)`: eine Beschreibung pro Argument, die das Modell zusätzlich zum Docstring liest.
* `Field(ge=1, le=50)`: numerische Grenzen. Sie landen im Schema als `"minimum": 1, "maximum": 50`.
* `Literal["fiction", "non-fiction", "poetry"]`: ein Enum. Das Modell kann nur einen dieser Werte wählen.

!!! check
    Constraints sind keine Dekoration. Ruf das Tool mit `limit=999` auf, und das SDK antwortet mit einem
    Tool-Fehler, **bevor deine Funktion läuft**:

    ```text
    Input should be less than or equal to 50
    ```

    Dieser Fehler geht als Tool-Ergebnis zurück an das Modell, das Modell liest ihn und versucht es mit
    einem gültigen Wert erneut. Du hast einmal `le=50` geschrieben und bekommst selbstkorrigierende Agenten umsonst dazu.

!!! info
    Wenn du FastAPI oder Pydantic schon benutzt hast, kennst du das alles bereits. Es ist dasselbe `Field`,
    dasselbe `Annotated`, dieselbe Validierung. Es gibt hier nichts MCP-Spezifisches zu lernen.

## Ein Modell als Parameter {#a-model-as-a-parameter}

Nimmt ein Tool mehr als ein paar Argumente entgegen, fasse sie in einem Pydantic-Modell zusammen:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

Das `Book`-Schema wird in das Eingabeschema des Tools eingebettet (als `$defs`-Referenz), das Modell füllt es als JSON-Objekt aus, und deine Funktion erhält eine **echte `Book`-Instanz**, bereits validiert, mit den Attributen `.title`, `.author` und `.year`.

Du kannst frei kombinieren: einfache Parameter neben Modell-Parametern, verschachtelte Modelle, Listen von Modellen. Es ist Pydantic bis ganz nach unten.

## `async def` {#async-def}

Macht ein Tool I/O (ruft eine API auf, liest eine Datei, fragt eine Datenbank ab), deklariere es als `async def` und verwende `await` darin. Das SDK wartet darauf.

Ein Tool mit einfachem `def` funktioniert auch: Das SDK führt es in einem Thread aus, damit es den Server nie blockiert.

Mehr gibt es nicht zu konfigurieren.

## Namen, Titel und Annotationen {#names-titles-and-annotations}

Alles, was das SDK ableitet, kannst du im Dekorator überschreiben:

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` ist ein menschenlesbarer Name für UIs. Clients zeigen *„Search the catalog“* statt `search_books`.
* `annotations` sind **Hinweise** zum Verhalten für den Client:
  * `read_only_hint=True`: Dieses Tool ändert nichts.
  * `open_world_hint=False`: Es arbeitet auf einer geschlossenen Menge von Dingen (diesem Katalog), nicht im offenen Web.
  * Die beiden anderen, `destructive_hint` und `idempotent_hint`, beschreiben ein Tool, das *schreibt*: Darf es
    etwas löschen, und ist zweimal aufrufen dasselbe wie einmal aufrufen? Die Spezifikation definiert beide
    nur für Tools, die nicht read-only sind, deshalb würden sie bei `search_books` nichts aussagen.

Ein gut erzogener Client nutzt sie, um Dinge zu entscheiden wie *„Muss ich die Person fragen, bevor ich das ausführe?“*. Es sind Hinweise, keine Sicherheit. Verlass dich nie darauf, dass ein Client sie beachtet.

!!! tip
    `@mcp.tool()` akzeptiert auch `name=` und `description=`, falls du sie nicht aus dem Funktionsnamen
    und dem Docstring ableiten lassen willst. Meistens willst du das aber.

## Zusammenfassung {#recap}

* `@mcp.tool()` auf einer Funktion macht sie zum Tool. Name aus der Funktion, Beschreibung aus dem Docstring.
* Type Hints **sind** das Eingabeschema. Standardwerte machen Argumente optional.
* `Annotated[..., Field(...)]` fügt Beschreibungen und Constraints hinzu; `Literal` fügt Enums hinzu.
* Über einen Pydantic-Modell-Parameter nimmst du einen strukturierten „Body“ entgegen.
* Ungültige Argumente werden für dich abgewiesen, mit einem Fehler, den das Modell lesen und aus dem es sich erholen kann.
* `async def` für I/O, einfaches `def` für alles andere.

**[Strukturierte Ausgabe](structured-output.md)** beschreibt, was mit dem Wert passiert, den du mit `return` zurückgibst.
