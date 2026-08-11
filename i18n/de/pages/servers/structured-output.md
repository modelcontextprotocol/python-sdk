---
translation:
  sections: [a838d57f003aed44, 857d03886a0137ed, 42d9efcb9f542867, 2290ff08435b5573, e866c192e11d1c14, 6cdbad079f7b47f0, d4b607372fb28b51, 18dbf726ac45e0b7, c6f7d2a148aa49f4, c851964bb3301907, d715db6f8dccc9cc, ef86634aa70498a7]
  tool: 1
---
# Strukturierte Ausgabe {#structured-output}

Ein Tool, das einen einfachen `str` zurückgibt, liefert das Ergebnis doppelt: als Text in `content` und als `{"result": "..."}` in `structured_content`.

Auf dieser Seite geht es um diesen zweiten Kanal: woher er kommt, welche Formen er annehmen kann und wie das SDK dafür sorgt, dass er hält, was er verspricht.

Die Kurzfassung: **Die Annotation des Rückgabetyps ist das Ausgabeschema**. Du hast sie schon geschrieben.

## Das Ausgabeschema {#the-output-schema}

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial001.py"
```

Die entscheidende Zeile ist die Signatur: `-> int`.

Ihretwegen trägt das Tool, das das SDK bei `tools/list` sendet, ein `output_schema` neben dem Eingabeschema, das es aus deinen Parametern baut (darum kümmert sich **[Tools](tools.md)**):

```json
{
  "properties": {
    "result": {"title": "Result", "type": "integer"}
  },
  "required": ["result"],
  "title": "get_temperatureOutput",
  "type": "object"
}
```

Ein nackter `int` ist kein JSON-Objekt, also **verpackt** das SDK ihn in `{"result": ...}`. Ruf das Tool auf, und beide Kanäle sind gefüllt:

```python
result.content             # [TextContent(text="17")]
result.structured_content  # {"result": 17}
```

Jeder skalare Wert bekommt dieselbe Hülle: `str`, `int`, `float`, `bool`, `bytes`, `None`.

## Zwei Kanäle {#two-channels}

Warum denselben Wert zweimal senden?

* `content` ist für das **Modell**. Ein Sprachmodell liest Text; das ist der einzige Teil des Ergebnisses, den es sieht.
* `structured_content` ist für die **Anwendung**, in der das Modell läuft: Code, der `17` will und keinen Satz, in dem „17“ vorkommt.
* `output_schema` ist der Vertrag zwischen beiden, veröffentlicht, bevor das Tool überhaupt aufgerufen wird.

Du gibst einen einzigen Python-Wert zurück. Das SDK füllt alle drei.

## Ein Modell zurückgeben {#return-a-model}

Deklariere die Form als Pydantic-`BaseModel` und gib eine Instanz zurück:

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/structured_output/tutorial002.py"
```

`WeatherData` **ist** jetzt das Schema. Keine Hülle, kein `result`-Schlüssel:

```json
{
  "properties": {
    "temperature": {"description": "Degrees Celsius.", "title": "Temperature", "type": "number"},
    "humidity": {"description": "Relative humidity, 0 to 1.", "title": "Humidity", "type": "number"},
    "conditions": {"title": "Conditions", "type": "string"}
  },
  "required": ["temperature", "humidity", "conditions"],
  "title": "WeatherData",
  "type": "object"
}
```

`structured_content` ist das Objekt, Feld für Feld:

```python
result.structured_content  # {"temperature": 16.2, "humidity": 0.83, "conditions": "Overcast"}
```

Und das Modell geht nicht leer aus. Das SDK serialisiert dasselbe Objekt für `content` zu JSON-Text:

```json
{
  "temperature": 16.2,
  "humidity": 0.83,
  "conditions": "Overcast"
}
```

Beachte, dass das `Field(description=...)` an `temperature` und `humidity` im Schema gelandet ist. Dasselbe `Field`, das deine **Eingaben** beschrieben hat, beschreibt auch deine Ausgaben.

!!! info
    Wenn du FastAPIs `response_model` kennst, kennst du das hier schon: ein Pydantic-Modell als deklarierte
    Response, für dich serialisiert und dokumentiert. Der einzige Unterschied: Hier ist die Annotation des
    Rückgabetyps die ganze Deklaration.

## Ein `TypedDict` {#a-typeddict}

Nicht jede Form verdient eine Klasse. Ein `TypedDict` erzeugt dasselbe Schema:

```python title="server.py" hl_lines="8"
--8<-- "docs_src/structured_output/tutorial003.py"
```

Ein `TypedDict` ist zur Laufzeit ein einfaches `dict`, also baust du genau das und gibst es zurück. Das Schema, die Validierung und `structured_content` sind identisch mit der `BaseModel`-Variante (abgesehen von den Beschreibungen, für die ein `TypedDict` keinen Platz hat).

## Eine Dataclass {#a-dataclass}

Dataclasses funktionieren auch, genauso wie jede gewöhnliche Klasse, deren Attribute Type Hints tragen. Das SDK baut unter der Haube aus den Annotationen ein Pydantic-Modell.

```python title="server.py" hl_lines="8-9"
--8<-- "docs_src/structured_output/tutorial004.py"
```

Drei Schreibweisen, ein Schema. Nimm die, die deine Codebasis ohnehin schon verwendet.

## Listen {#lists}

Eine `list[...]` ist ebenfalls kein JSON-Objekt, also bekommt sie die `{"result": ...}`-Hülle, mit deinem Elementtyp als `$defs`-Referenz darin:

```python title="server.py" hl_lines="15"
--8<-- "docs_src/structured_output/tutorial005.py"
```

```json
{
  "$defs": {
    "WeatherData": {
      "properties": {
        "temperature": {"title": "Temperature", "type": "number"},
        "humidity": {"title": "Humidity", "type": "number"},
        "conditions": {"title": "Conditions", "type": "string"}
      },
      "required": ["temperature", "humidity", "conditions"],
      "title": "WeatherData",
      "type": "object"
    }
  },
  "properties": {
    "result": {"items": {"$ref": "#/$defs/WeatherData"}, "title": "Result", "type": "array"}
  },
  "required": ["result"],
  "title": "get_forecastOutput",
  "type": "object"
}
```

Fordere eine Zwei-Tage-Vorhersage an, und `structured_content` ist `{"result": [{...}, {...}]}`. `content` wird zu **zwei** `TextContent`-Blöcken, einer pro Element: Eine Liste wird für das Modell aufgefächert, statt als ein einziger String ausgegeben zu werden.

`tuple[...]`, Unions und `Optional[...]` werden genauso verpackt.

## Dictionaries {#dictionaries}

`dict[str, ...]` ist der eine generische Typ, der bereits ein JSON-Objekt *ist*, und wird deshalb nicht verpackt:

```python title="server.py" hl_lines="9"
--8<-- "docs_src/structured_output/tutorial006.py"
```

```json
{
  "additionalProperties": {"type": "number"},
  "title": "get_temperaturesDictOutput",
  "type": "object"
}
```

```python
result.structured_content  # {"London": 16.2, "Reykjavik": 4.4}
```

Die Schlüssel müssen `str` sein. Ein `dict[int, float]` kann kein JSON-Objekt sein und fällt deshalb auf die `{"result": ...}`-Hülle zurück.

## Validierung {#validation}

`output_schema` ist keine Dokumentation. Was auch immer deine Funktion zurückgibt, wird **dagegen validiert**, bevor es den Server verlässt.

Solange du den Wert von Hand baust, merkst du davon nichts: Pydantic hat schon sichergestellt, dass dein `WeatherData` ein `WeatherData` ist. Du merkst es an dem Tag, an dem die Daten von irgendwo kommen, das du nicht kontrollierst:

```python title="server.py" hl_lines="9 21"
--8<-- "docs_src/structured_output/tutorial007.py"
```

Die Annotation verspricht `WeatherData`. Die Upstream-Response liefert `humidity` nicht mehr mit.

!!! check
    Ruf `get_weather` auf, und es reicht dem Client nicht stillschweigend ein halb leeres Objekt weiter. Der Aufruf schlägt fehl,
    und die ersten Zeilen des Fehlers nennen das Feld:

    ```text
    Error executing tool get_weather: 1 validation error for WeatherData
    humidity
      Field required [type=missing, input_value={'temperature': 16.2, 'conditions': 'Overcast'}, input_type=dict]
    ```

    Dieser Text kommt als Tool-Ergebnis mit `is_error=True` zurück. So weiß das Modell, dass der Aufruf fehlgeschlagen ist,
    statt selbstbewusst Wetterdaten abzulesen, die gar nicht da sind.

Ein einfaches `dict` aus einem `-> WeatherData`-Tool zurückzugeben ist übrigens in Ordnung. Genau das hat `json.loads` erzeugt. Validiert wird der Wert, nicht der Python-Typ.

## Abschalten {#opting-out}

Manchmal ist die Annotation des Rückgabetyps für den Type Checker da, nicht für das Protokoll. Übergib `structured_output=False`, und das Tool liefert nur Text:

```python title="server.py" hl_lines="6"
--8<-- "docs_src/structured_output/tutorial008.py"
```

Kein `output_schema`, keine Hülle, keine Validierung. `structured_content` ist `None`, und `content` ist der String, den du zurückgegeben hast.

Das Gegenteil, `structured_output=True`, macht aus der automatischen Erkennung eine Anforderung: Ein Tool, dessen Rückgabetyp kein Schema erzeugen kann, löst beim Import eine Exception aus, statt auf Text zurückzufallen.

## Eine Klasse ohne Type Hints {#a-class-without-type-hints}

Es gibt einen Weg, unstrukturiert zu enden, ohne es gewollt zu haben: eine Klasse zurückzugeben, die **keine Annotationen im Klassenrumpf** hat.

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/structured_output/tutorial009.py"
```

`Station` setzt `name` und `online` in `__init__`, aber die *Klasse* deklariert nichts. Das SDK liest die Klassenannotationen, findet keine und gibt auf.

!!! warning
    Es gibt **stillschweigend** auf. `output_schema` ist `None`, `structured_content` ist `None`, und der Text,
    den das Modell liest, ist das `repr` des Objekts:

    ```text
    "<server.Station object at 0x7f539d75b230>"
    ```

    Kein Fehler, keine Warnung, ein nutzloses Tool. Verschiebe die Annotationen in den Klassenrumpf oder übergib
    `structured_output=True`. Das macht daraus einen harten Fehler, sobald das Modul importiert wird:
    `Function get_station: return type <class 'server.Station'> is not serializable for structured output`.

!!! tip
    Brauchst du die volle Kontrolle (das `CallToolResult` selbst bauen oder `_meta` anhängen, das die
    Anwendung sieht, das Modell aber nicht)? Das ist **[Der Low-Level-Server](../advanced/low-level-server.md)**.

## Zusammenfassung {#recap}

* Die **Annotation des Rückgabetyps** ist das Ausgabeschema. Sie wird in `tools/list` als `output_schema` veröffentlicht.
* Skalare, Listen, Tupel und Unions werden in `{"result": ...}` verpackt. Modelle, `TypedDict`s, Dataclasses, annotierte Klassen und `dict[str, ...]` sind schon Objekte und bleiben, wie sie sind.
* Jedes Ergebnis trägt `content` (Text, für das Modell) **und** `structured_content` (Daten, für die Anwendung).
* Was du zurückgibst, wird gegen das Schema validiert. Eine Abweichung ist ein Tool-Fehler, kein kaputtes Ergebnis.
* `structured_output=False` nimmt ein Tool davon aus. Eine Klasse ohne Type Hints nimmt sich stillschweigend aus; achte darauf.

Damit hast du alles in der Hand, was ein Tool zurückmelden kann. Als Nächstes das zweite Primitiv: **[Ressourcen](resources.md)**.
