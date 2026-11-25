---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# Abbruch {#cancellation}

Ein Client kann einen Aufruf aufgeben: Die Person am Host hat auf Stopp gedrückt, oder ein Timeout ist abgelaufen.

In diesem Fall **bricht das SDK deinen Handler ab**. Das `await`, an dem er gerade wartet, löst eine Exception aus, die Funktion wird abgewickelt, und nichts, was sie zurückgibt, wird gesendet. Die meisten Handler müssen dafür nichts tun.

Für zwei Arten gilt das nicht: einen Handler, der etwas aufzuräumen hat, und einen Handler, der ein einfaches `def` ist.

## In einem `async def`-Tool aufräumen {#clean-up-in-an-async-def-tool}

Lege den Aufräumcode in ein `finally`:

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* Das `finally` läuft, egal wie das Tool endet: ob es zurückgekehrt ist, eine Exception ausgelöst hat oder abgebrochen wurde.
* Aufräumcode, der `await` verwenden muss, braucht `shield=True`. In einem abgebrochenen Handler löst auch jedes weitere `await` eine Exception aus. Ohne die Abschirmung würde `release_hold` also schon in seiner ersten Zeile stoppen.
* Einen abgeschirmten Block kann nichts abbrechen, gib ihm also ein Zeitlimit. Hier sind das `5` Sekunden.

!!! tip
    Greife zu `finally`, nicht zu `except`. Der Abbruch muss weiter nach oben wandern, sobald du
    aufgeräumt hast, und ein `finally` lässt das zu.

## In einem einfachen `def`-Tool vorzeitig stoppen {#stop-early-in-a-plain-def-tool}

Ein einfaches `def`-Tool läuft in einem Thread, und einen Thread kann nichts von außen unterbrechen. Das Tool muss selbst nachfragen:

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` tut nichts, solange der Aufruf aktiv ist, und löst eine Exception aus, sobald er abgebrochen wurde. Rufe die Funktion zwischen den einzelnen Arbeitsschritten auf.
* Auch hier gehört der Aufräumcode in ein `finally`. In einem Thread gibt es kein await, er braucht also keine Abschirmung.
* Ein `def`-Tool, das nie nachfragt, läuft bis zum Ende, und sein Ergebnis wird verworfen.

## Geltungsbereich {#where-it-applies}

Prompt- und Ressourcenfunktionen werden genauso abgebrochen wie Tools.

Über stdio und Streamable HTTP funktioniert das gleich. Mit dem `Client` dieses SDK heißt aufgeben: den Task abbrechen, der auf `call_tool` wartet, oder dessen `read_timeout_seconds` ablaufen lassen.

!!! warning
    Bei zwei Streamable-HTTP-Optionen erfährt dein Handler nichts davon: `json_response=True` auf einer
    `2026-07-28`-Verbindung und `stateless_http=True` auf einer Legacy-Verbindung. Dort läuft der Handler
    bis zum Ende, egal was der Client getan hat.

## Zusammenfassung {#recap}

* Gibt der Client einen Aufruf auf, bricht das SDK den Handler ab: Tool, Prompt oder Ressource.
* `async def`: Räume in einem `finally` auf und lege Aufräumcode, der await braucht, in `anyio.move_on_after(seconds, shield=True)`.
* Einfaches `def`: Rufe zwischen den Arbeitsschritten `anyio.from_thread.check_cancelled()` auf, sonst läuft das Tool bis zum Ende. Zum Aufräumen genügt ein einfaches `finally`.
* `json_response=True` (moderne Verbindungen) und `stateless_http=True` (Legacy-Verbindungen) schalten den Abbruch ab.

Fortschritt und Abbruch spielen sich zwischen einem laufenden Tool und seinem *Aufrufer* ab. Die Zeilen, die es für *dich* loggt, also für die Person, die den Server betreibt, sind ein anderer Kanal: **[Logging](logging.md)**.
