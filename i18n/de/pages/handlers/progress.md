---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# Fortschritt {#progress}

Ein Tool, das dreißig Sekunden braucht und dreißig Sekunden lang schweigt, wirkt kaputt.

**Fortschrittsbenachrichtigungen** beheben das. Das Tool meldet, wie weit es ist; der Client entscheidet, was er daraus zeichnet: einen Balken, einen Spinner, eine Log-Zeile.

## Aus dem Tool melden {#report-it-from-the-tool}

Nimm einen **`Context`**-Parameter entgegen und rufe `report_progress` auf:

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

Drei Argumente, und du bestimmst, was sie bedeuten:

* `progress`: wie weit du bist. Die Spezifikation verlangt, dass der Wert mit jeder Meldung **steigt**; wiederhole nie einen Wert und geh nie rückwärts.
* `total`: wie viel es insgesamt ist, falls du es weißt. Optional.
* `message`: eine menschenlesbare Zeile über *diesen* Schritt. Optional.

`ctx` wird wegen seines Type Hints injiziert, und das Modell sieht ihn nie: Das Eingabeschema von `import_catalog` hat eine einzige Property, `urls`. Die Seite **[Der Context](context.md)** dreht sich ganz um dieses Objekt; Fortschritt ist eines der Dinge, die es dir bietet.

## Im Client darauf lauschen {#listen-for-it-from-the-client}

Der Client meldet sich **pro Aufruf** an, indem er `progress_callback=` an `call_tool` übergibt:

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

Der Callback ist eine `async`-Funktion, die genau das entgegennimmt, was der Server gemeldet hat: `progress`, `total`, `message`.

!!! info
    `Client(mcp)` verbindet sich direkt mit dem Server-Objekt, im Speicher – derselbe Client, auf dem die Seite
    **[Testen](../get-started/testing.md)** aufbaut. `progress_callback` ist derselbe Parameter, egal welchen
    Transport der `Client` nutzt; das *Timing*, das du gleich siehst, ist das der In-Memory-Verbindung. Sie führt
    deinen Callback inline aus, sodass jede Meldung eintrifft, bevor `call_tool` zurückkehrt. Über einen echten
    Transport liefern sich die Benachrichtigungen ein Rennen mit dem Ergebnis, und ein langsamer Callback kann noch
    laufen, nachdem `call_tool` bereits zurückgekehrt ist.

### Ausprobieren {#try-it}

Lege `client.py` neben `server.py` und starte es:

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

Jedes `await ctx.report_progress(...)` auf dem Server wurde zu einem Aufruf von `show` auf dem Client, in derselben Reihenfolge, und beide Zeilen wurden ausgegeben, **bevor** `call_tool` zurückkehrte. Fortschritt wird nicht ins Ergebnis gepackt; er streamt, während das Tool noch arbeitet.

!!! warning
    `progress_callback` gehört zum **Aufruf**, nicht zum `Client`. Es gibt kein Konstruktorargument dafür,
    weil verschiedene Aufrufe verschiedene Callbacks wollen: Einer treibt einen Download-Balken an, der nächste
    eine Log-Zeile.

!!! check
    Lösche jetzt `progress_callback=show` und starte es erneut:

    ```text
    {'result': 'Imported 2 records.'}
    ```

    Kein Fehler, keine Warnung, dasselbe Ergebnis. `report_progress` ist ein **No-op, wenn der Aufrufer keinen
    Fortschritt angefordert hat**. Du meldest also bedingungslos und musst dich nie fragen, ob überhaupt jemand
    zuhört.

## Wenn du die Gesamtmenge nicht kennst {#when-you-dont-know-the-total}

`total` ist für den Fall, dass du den Nenner kennst. Oft kennst du ihn nicht: Du leerst einen Feed, läufst einen Cursor ab, lädst etwas ohne Längen-Header herunter.

Lass es weg:

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

Der Callback erhält `total=None`. Ein Client kann weiterhin *Aktivität* anzeigen („3 imported so far...“), aber keinen Prozentwert. Erfinde keine Gesamtmenge, nur um einen hübscheren Balken zu bekommen.

!!! tip
    `progress` muss nichts Bestimmtes zählen. Bytes, Zeilen, Seiten: Wähle die Einheit, die die Person am Host
    wiedererkennt, und versprich nur ein `total`, das du halten kannst.

## Zusammenfassung {#recap}

* `await ctx.report_progress(progress, total=None, message=None)` aus jedem Tool, das einen `Context` entgegennimmt.
* Der Client übergibt `progress_callback=` an `call_tool`: pro Aufruf, nie am `Client`.
* Der Callback ist `async (progress, total, message) -> None` und feuert, während das Tool noch läuft.
* Kein Callback am Aufruf heißt: `report_progress` tut nichts. Melde bedingungslos.
* Lass `total` weg, wenn du es nicht kennst; der Callback bekommt `None`.

Fortschritt ist das, was ein laufendes Tool der *Person am Host* zeigt. Die Zeilen, die es für *dich* loggt – für dich, weil du den Server betreibst –, sind ein anderer Kanal: **[Logging](logging.md)**.
