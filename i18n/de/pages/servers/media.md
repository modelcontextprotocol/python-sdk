---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# Medien {#media}

Text ist nicht das Einzige, was ein Tool zurückgeben kann.

Das SDK bringt zwei Helfer für binäre Ergebnisse mit (**`Image`** und **`Audio`**) sowie einen Typ **`Icon`**, mit dem dein Server, deine Tools, Ressourcen und Prompts im UI des Clients ein Gesicht bekommen.

## Ein Bild zurückgeben {#returning-an-image}

Annotiere den Rückgabetyp als `Image`, zeige auf eine Datei und gib sie zurück:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` nimmt genau eines von `path` (eine Datei, die gelesen wird) oder `data` (rohe Bytes).
* Den MIME-Typ, den der Client sieht, errät das SDK aus der Dateiendung: `logo.png` wird als `image/png` angekündigt.
* Nichts hiervon ist speziell für Logos. Jedes PNG neben `server.py` funktioniert: ein Diagramm, das dein Code gerendert hat, eine Skizze, ein Foto.

`Image` ist eine Bequemlichkeit des SDK, kein Protokolltyp. Auf der Leitung wird dein Rückgabewert zu einem **`ImageContent`**-Block (die Bytes der Datei base64-kodiert, dazu der MIME-Typ):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

Zwei Dinge fallen auf:

* `data` ist base64. Du hast die Bytes nie angefasst; das SDK hat die Datei gelesen und kodiert.
* `structured_content` ist `None`. Ein `Image` ist Inhalt, den das Modell anschaut, keine Daten, die die Anwendung parst: Es gibt kein Output-Schema. (Vergleiche **[Strukturierte Ausgabe](structured-output.md)**, wo die Rückgabeannotation das Schema *ist*.)

!!! info
    `ImageContent` und `AudioContent` liegen in `mcp.types`, direkt neben dem `TextContent`,
    zu dem ein einfaches `str`-Ergebnis wird (**[Tools](tools.md)**). Ein Tool-Ergebnis ist eine Liste von Content-Blöcken; `Image` und `Audio` sind
    der kürzeste Weg, die beiden binären Arten zu erzeugen.

### Ausprobieren {#try-it}

Lege ein beliebiges PNG neben `server.py`, nenne es `logo.png` und starte:

```console
uv run mcp dev server.py
```

Öffne den Tab **Tools** und rufe `logo` auf. Das Ergebnis ist kein String: Es ist ein Content-Block vom Typ `image`, und der Inspector rendert dein Bild. Alles zwischen der Datei auf der Platte und den Pixeln auf dem Bildschirm hat das SDK erledigt.

## Audio zurückgeben {#returning-audio}

`Audio` hat dieselbe Form. Lass `logo.png`, wo es war, und lege eine beliebige WAV-Datei als `chime.wav` daneben:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

Das Ergebnis ist ein **`AudioContent`**-Block:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

Dasselbe Prinzip: eine Datei auf der Platte hinein, base64 und ein MIME-Typ heraus, kein Output-Schema.

## Bytes oder eine Datei {#bytes-or-a-file}

Beide Helfer akzeptieren auch `data=` (rohe Bytes) statt `path=`. Das ist der Modus für Bytes, die nie aus einer eigenen Datei kamen – eine Datenbankspalte, eine HTTP-Response, etwas, das Pillow gerade gezeichnet hat:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

Mit `path=` gibt es nichts zu deklarieren: Die Datei wird gelesen, wenn das Ergebnis gebaut wird, und der MIME-Typ wird aus der Endung erraten:

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

Eine Endung, die nicht erkannt wird, fällt auf `application/octet-stream` zurück.

!!! check
    Mit `data=` gibt es keinen Dateinamen, also nichts, woraus sich etwas erraten ließe. Vergisst du `format=`,
    fällt das SDK auf einen Standardwert zurück: `image/png` für Bilder, `audio/wav` für Audio. Baust du so ein
    `Audio` aus MP3-Bytes, bekommt der Client `mime_type="audio/wav"` mitgeteilt und scheitert dann
    folgerichtig am Dekodieren. Wenn du `data=` übergibst, übergib auch `format=`.

## Icons {#icons}

Ein `Icon` ist Metadaten, kein Inhalt. Es trägt das Bild nicht; es zeigt per URI auf eines, und ein Client kann es abrufen und neben dem Namen deines Servers, einem Tool, einer Ressource oder einem Prompt anzeigen.

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` ist ein URI, den der Client auflösen kann: `https:` oder ein `data:`-URI, wenn du das Icon ohne zusätzlichen Abruf einbetten willst.
* Mit `mime_type` und `sizes` (`"48x48"` oder `"any"` für ein skalierbares Format) kann der Client das passende auswählen, wenn du mehrere anbietest.
* `theme="light"` oder `theme="dark"` markiert ein Icon für ein Farbschema.

Dasselbe Keyword `icons=[...]` akzeptieren `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()` und `@mcp.prompt()`.

### Wo ein Client sie sieht {#where-a-client-sees-them}

Icons reisen mit dem, was sie schmücken. Die des Servers kommen an, wenn sich der Client verbindet, auf `client.server_info` (auf Verbindungen der 2026er-Generation optional, also grenze es zuerst ein):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

Die Icons eines Tools liegen auf dem `Tool`-Objekt aus `tools/list`, die einer Ressource auf der `Resource` aus `resources/list`, die eines Prompts auf dem `Prompt` aus `prompts/list`. Das Feld heißt immer `icons`.

## Zusammenfassung {#recap}

* Gib ein `Image` oder `Audio` aus einem Tool zurück, und der Client empfängt einen `ImageContent`- bzw. `AudioContent`-Block: deine Bytes base64-kodiert, mit einem MIME-Typ.
* Baue eines aus einem `path=` und lass die Endung den MIME-Typ bestimmen, oder aus `data=` im Speicher plus einem expliziten `format=`.
* Medien-Ergebnisse tragen kein `structured_content` und kein Output-Schema.
* Ein `Icon` ist ein Zeiger: ein `src`-URI plus optional `mime_type`, `sizes` und `theme`.
* `icons=[...]` funktioniert auf dem Server, auf Tools, auf Ressourcen und auf Prompts, und Clients finden sie auf den passenden Objekten.

Das ist alles, was ein Tool *in* ein Ergebnis packen kann. Was passiert, wenn ein Tool *fehlschlägt* (und wer davon erfahren sollte), steht in **[Fehler behandeln](handling-errors.md)**.
