---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# Header-Parameter {#header-parameters}

Die meisten Server brauchen das nie.

Ein Gateway oder Load Balancer vor deinem Server kann nur anhand dessen routen, was er lesen kann, ohne den Body zu parsen. Markiere ein Tool-Argument mit `x-mcp-header`, und Clients mit der **[Protokollversion](../protocol-versions.md)** `2026-07-28` senden seinen Wert zusätzlich als HTTP-Header.

## Ein Argument markieren {#mark-an-argument}

Die Markierung ist ein zusätzlicher Schlüssel im JSON Schema des Arguments. Bei `MCPServer` setzt `Field` ihn dort:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* Über Streamable HTTP mit `2026-07-28` sendet ein Client `Mcp-Param-Region` zusätzlich zum Body, und der Server lehnt einen Aufruf ab, bei dem beide nicht übereinstimmen.
* Ein Client, der das Tool nicht aufgelistet hat, hat die Markierung nie gesehen: Er sendet keinen Header, und der Aufruf wird abgelehnt. Der `Client` dieses SDK listet dann die Tools auf und sendet den Aufruf einmal erneut. Vorher aufzulisten spart also nur einen Roundtrip.
* Jede andere Verbindung ignoriert die Annotation.

Deine Funktion ändert sich nicht: `region` kommt weiterhin als Argument an.

## Was sich markieren lässt {#what-can-be-marked}

Argumente vom Typ `str`, `int` und `bool`. Alles andere wird beim Registrieren des Tools mit `InvalidSignature` abgewiesen.

Das gilt auch für `str | None`, das keinen einzelnen Typ hat. Ein optionales Argument braucht ein ausgeschriebenes Schema, mit `WithJsonSchema` von Pydantic:

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## Beim Low-Level-`Server` {#on-the-low-level-server}

Dort schreibst du `input_schema` von Hand, der Schlüssel kommt also direkt hinein:

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* Nichts prüft die Annotation für dich: Eine ungültige wird ausgeliefert, und `2026-07-28`-Clients lassen das Tool aus ihrer Auflistung weg.

### Schemas nach Namen {#schemas-by-name}

Um den Header zu prüfen, braucht das SDK das Eingabeschema des Tools, bevor es den Aufruf weiterleitet. Ohne `get_tool_input_schema` holt es sich das Schema, indem es bei jedem Aufruf mit Argumenten deinen `on_list_tools`-Handler ausführt – egal, ob überhaupt ein Tool markiert ist.

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* Übergib die Funktion, um aus dem zu antworten, was du schon hast.
* Gib `None` für ein Tool zurück, bei dem es nichts zu prüfen gibt.

## Zusammenfassung {#recap}

* `x-mcp-header` an einem Tool-Argument sorgt dafür, dass `2026-07-28`-Clients es als HTTP-Header `Mcp-Param-*` wiederholen.
* Der Server lehnt einen Aufruf ab, bei dem Header und Body nicht übereinstimmen.
* Nur Argumente vom Typ `str`, `int` und `bool` lassen sich markieren. Bei allem anderen löst `MCPServer` `InvalidSignature` aus.
* Der Low-Level-`Server` prüft nichts, und Clients verwerfen ein Tool mit ungültiger Annotation.
* `get_tool_input_schema` verhindert, dass der Low-Level-`Server` bei jedem Aufruf `on_list_tools` ausführt.

Der Rest der handgeschriebenen `Server`-API steht in **[Der Low-Level-Server](low-level-server.md)**.
