---
translation:
  sections: [e33d441f12d50535, 7099694c603e0f5f, c1df4cf9673433e6, c9cd294541422e6e, 6cec073617bfd037, efa92b8f99e908c8, 6a22a29e27fb4601]
  tool: 1
---
# Fehler behandeln {#handling-errors}

Ein Tool kann auf zwei Arten scheitern, und das SDK behandelt sie sehr unterschiedlich.

Löse eine gewöhnliche Exception aus, und das **Modell** sieht sie. Löse `MCPError` aus, und das **Protokoll** sieht sie.

Auf dieser Seite geht es um die Wahl zwischen beiden.

## Ein Fehler, den das Modell beheben kann {#an-error-the-model-can-fix}

Nimm ein Tool, das etwas nachschlägt, und lass das Nachschlagen ins Leere laufen:

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

An diesen zwei Zeilen ist nichts MCP-Spezifisches. `get_author` löst einen schlichten `ValueError` aus, so wie es jede Python-Funktion täte.

Ruf es mit einem Titel auf, der nicht im Katalog steht, und sieh dir das Ergebnis an:

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* Der Request war **erfolgreich**. Es gibt ein Ergebnis; beim Aufrufer wurde nichts ausgelöst.
* `is_error` ist `True`, und die Meldung deiner Exception (mit dem Tool-Namen als Präfix) steht in `content` – genau dort, wo das Modell liest.
* `structured_content` ist `None`. Ein fehlgeschlagener Aufruf hat keinen Rückgabewert, den man strukturieren könnte.

Das ist ein **Tool-Fehler**, und er ist der Standard für *jede* Exception, die dein Tool auslöst. Fast immer ist es auch genau das, was du willst.

Das Modell ist es, das dein Tool aufruft. Es hat die Argumente gewählt. Ein Tool-Fehler ist also ein Zug im Gespräch: Das Modell liest *„No book titled 'Nothing' in the catalog.“*, merkt, dass es den Titel falsch geraten hat, und ruft erneut mit einem besseren auf. Du hast ein einziges `raise` geschrieben und einen sich selbst korrigierenden Agenten bekommen.

!!! tip
    Gib aus einem Tool nie eine Fehlermeldung per `return` zurück. Ein zurückgegebener String hat `is_error=False`;
    für das Modell (und für jede Client-UI) sieht es also aus, als hätte das Tool funktioniert und dieser String
    wäre die Antwort. `raise`. Das Flag ist das Signal.

## Ein Fehler, den das Modell nicht beheben kann {#an-error-the-model-cannot-fix}

Tausche jetzt `ValueError` gegen `MCPError`.

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` ist der **Protokollfehler** des SDK. Es ist die eine Exception, die der Tool-Wrapper *nicht* abfängt: Sie wird weitergereicht, und der ganze `tools/call`-Request schlägt mit einem JSON-RPC-Fehler fehl statt mit einem Ergebnis zu enden.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* Es gibt **kein Ergebnis**. Kein `content`, kein `is_error`: nichts, was das Modell lesen könnte.
* Stattdessen bekommt die **Host**-Anwendung den Fehler – genauso, als gäbe es das Tool gar nicht.
* `code`, `message` und `data` kommen unverändert an. `INVALID_PARAMS` ist `-32602`; `mcp.types` exportiert ihn und die anderen JSON-RPC-Fehlercodes (`INVALID_REQUEST`, `INTERNAL_ERROR`, ...) als Konstanten, sodass du nie eine magische Zahl tippen musst.

!!! check
    Dasselbe Nachschlagen, derselbe Fehlschlag, aber jetzt *löst* der Aufruf auf der Client-Seite eine Exception *aus*, statt zurückzukehren:

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    Die erste Version gab dem Modell einen Satz, auf den es reagieren konnte. Diese hier gibt ihm nichts.
    Für `get_author` ist das eindeutig schlechter – und genau darum geht es im nächsten Abschnitt.

## Welche der beiden auslösen {#which-one-to-raise}

Die beiden Wege beantworten zwei verschiedene Fragen.

* **Löse irgendeine Exception aus** bei einem Fehlschlag der *Ausführung*: Das, was dein Tool versucht hat, hat nicht geklappt. Das Modell hat den Aufruf gewählt, also sollte das Modell die Folge sehen und die Chance bekommen, sich zu fangen. Ein falsch geschriebener Titel, eine vorgelagerte API mit Timeout, eine Zeile, die es nicht gibt: alles Tool-Fehler.
* **Löse `MCPError` aus**, wenn der *Request selbst* abgelehnt werden soll: Dem Client fehlt eine Capability, auf die dein Tool angewiesen ist, der Server ist nicht in einem Zustand, irgendwen zu bedienen, der Aufrufer hat einen erforderlichen Schritt übersprungen. Kein erneuter Versuch des Modells behebt irgendetwas davon, also bringt es nichts, ihm die Meldung zu geben.

Eine Frage entscheidet: **Hätte ein klügeres Modell das vermeiden können?** Ja -> gewöhnliche Exception. Nein -> `MCPError`.

Nach diesem Test hat die zweite Version von `get_author` die falsche Wahl getroffen: Ein besserer Titel behebt das Problem, also hätte das Modell die Meldung sehen sollen. Sie soll dir den Mechanismus zeigen, nicht ihn empfehlen.

!!! info
    `MCPError` findest du unter `from mcp import MCPError`; sie nimmt `code`, `message` und eine optionale
    `data`-Payload entgegen. Was immer du hineinlegst, bekommt der Client: Das SDK leitet eine ausgelöste
    `MCPError` wortwörtlich weiter, statt sie zu bereinigen.

## Eine Ressource, die es nicht gibt {#a-resource-that-doesnt-exist}

Ressourcen ziehen dieselbe Grenze und bringen für den häufigen Fall eine benannte Exception mit.

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` ist ein **Template**. Es passt auf *jeden* Titel, also sind „der URI ist wohlgeformt“ und „das Buch existiert“ zwei verschiedene Fragen, und nur deine Funktion kann die zweite beantworten.

Wenn sie das nicht kann, löse `ResourceNotFoundError` aus. Das SDK macht daraus den Protokollfehler, den die Spezifikation einer fehlenden Ressource zuordnet: `-32602` mit dem angeforderten URI in `data`, damit der Client weiß, *welcher* Lesevorgang fehlgeschlagen ist.

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

Beachte, dass es hier kein halbes Ergebnis mit `is_error=True` gibt. Das Lesen einer Ressource liefert entweder Inhalte oder schlägt fehl: Ressourcen haben nur den Protokollweg. Templates und alles Weitere zu Ressourcen stehen in **[Ressourcen](resources.md)**.

## Fehler, die du nie auslöst {#errors-you-never-raise}

Ein ungültiges Argument erreicht deine Funktion nie.

Schick `get_author` einen `title`, der kein String ist, und das SDK weist ihn anhand des Eingabeschemas ab, **bevor** es dich aufruft – als dieselbe Art Tool-Fehler mit `is_error=True`, den das Modell lesen und korrigieren kann. **[Tools](tools.md)** zeigt dieselbe Ablehnung mit einer `Field(le=50)`-Einschränkung.

Das bedeutet eine ganze Klasse von `raise`-Anweisungen, die du nicht schreibst: Validiere deine eigenen Type Hints nicht noch einmal.

!!! info
    Alles auf dieser Seite ist das, was ein **Client** sieht, und der In-Memory-`Client`, mit dem du
    Tests schreibst, sieht exakt dasselbe. Selbst `raise_exceptions=True` macht aus einem Tool-Fehler
    keinen Traceback mehr: Bis dieses Flag greifen könnte, ist deine Exception längst das
    Ergebnis mit `is_error=True`. Prüfe das Ergebnis mit Assertions. **[Testen](../get-started/testing.md)** beschreibt das Muster.

## Zusammenfassung {#recap}

* Löse **irgendeine Exception** in einem Tool aus -> der Aufruf gibt `is_error=True` mit deiner Meldung in `content` zurück. Das Modell liest sie und kann es erneut versuchen. Das ist der Standard.
* Löse **`MCPError`** aus -> der Aufruf selbst schlägt mit einem JSON-RPC-Fehler fehl. Das Modell sieht nichts; der Host kümmert sich darum. `code`, `message` und `data` kommen unverändert durch.
* Die entscheidende Frage: *Hätte ein klügeres Modell das vermeiden können?* Ja -> Exception. Nein -> `MCPError`.
* `ResourceNotFoundError` aus einem Ressourcen-Handler -> das `-32602` des Protokolls, mit dem URI in `data`.
* Ungültige Argumente werden anhand des Schemas abgewiesen, bevor deine Funktion läuft; dafür schreibst du kein `raise`.
* `from mcp import MCPError`; die Fehlercode-Konstanten kommen aus `mcp.types`.

Fehler behandelt. Das ist alles, was ein Server *nach außen anbietet*. Was jeder Handler lesen und während der Ausführung zurück an den Client tun kann, ist der nächste Abschnitt: **[Im Handler](../handlers/index.md)**.

Den genauen Wortlaut der SDK-Fehler, denen du am ehesten begegnest, was jeder bedeutet und wie du ihn jeweils mit einem Handgriff behebst, findest du unter **[Fehlerbehebung](../troubleshooting.md)**.
