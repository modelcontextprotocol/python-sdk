---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# Logging {#logging}

Logge aus einem Tool genauso wie aus jeder anderen Python-Funktion: mit der Standardbibliothek.

MCP hat auf Protokollebene eine **Capability für Logging**: Ein Server konnte seine Log-Meldungen über Methoden des `Context`-Objekts als Benachrichtigungen an den Client schicken. Die Revision 2026-07-28 der Spezifikation **erklärt diese Capability für veraltet und ersetzt sie nicht**, deshalb vermitteln diese Docs sie nicht. Die vollständige Liste dessen, was veraltet ist und was du stattdessen tust, steht in **[Veraltete Features](../deprecated.md)**.

Stattdessen tust du, was du in jedem anderen Python-Programm tust: Du nimmst die Standardbibliothek.

## Ein Tool, das loggt {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` liefert dir einen Logger, der nach deinem Modul benannt ist. Leg ihn einmal an, ganz oben.
* Im Tool rufst du `logger.info(...)` auf wie in jeder anderen Funktion. Nichts zu injizieren, nichts mit `await`, nichts MCP-Spezifisches.

!!! check
    Ruf das Tool auf und sieh dir das ganze Ergebnis an:

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    Die Log-Zeile taucht darin nirgends auf. Logging ist für **dich**, die Person, die den Server betreibt.
    Das Modell sieht es nie. Wenn das Modell etwas lesen soll, gib es mit `return` zurück.

## Wohin die Ausgabe geht {#where-it-goes}

Bei einem **stdio**-Server ist diese Frage wichtiger als sonst. Der Host hat deinen Server als Subprozess gestartet und liest MCP-Nachrichten von dessen **stdout**. Standard Error gehört dir.

Die Standardbibliothek macht bereits das Richtige: Log-Ausgaben gehen standardmäßig nach `sys.stderr`. Deine `logger.info(...)`-Zeilen landen im Terminal (oder wo auch immer der Host das stderr des Subprozesses einsammelt), und der Protokoll-Stream bleibt sauber.

!!! tip
    Verwende kein `print()` in einem stdio-Server. `print` schreibt nach **stdout**, und stdout gehört dem Protokoll.
    Während der Server läuft, leitet das SDK stdout, das tatsächlich *geflusht* wird, nach stderr um, sodass es die
    Leitung nicht beschädigen kann. Ein `print()` in einem blockgepufferten Prozess bleibt aber meist ungeflusht im
    Puffer von `sys.stdout` liegen, bis der Interpreter ihn beim Beenden leert – direkt auf den Protokoll-Stream.
    Selbst wenn die Zeile umgeleitet wird, landet sie roh zwischen den Log-Ausgaben, ohne Level, ohne Logger-Namen
    und ohne Möglichkeit, sie zu filtern.

    `logger.debug("got here")` ist dieselbe eine Zeile Aufwand und geht an die richtige Stelle.

## Das Level {#the-level}

Du musst `logging.basicConfig()` nicht selbst aufrufen. Das Erzeugen eines `MCPServer` hat das bereits getan, mit einem Handler, der auf Standard Error zeigt, auf dem Level, das du als `log_level=` übergibst. `MCPServer("Bookshop", log_level="DEBUG")` genügt also, um deine `logger.debug(...)`-Zeilen zu sehen.

Der Standardwert ist `"INFO"`.

`logging.basicConfig()` ersetzt nie Handler, die bereits existieren. Wenn du das Logging selbst konfigurierst, bevor du den Server erzeugst, gewinnt deine Konfiguration.

## Ausprobieren {#try-it}

Starte den Server mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Ruf `search_books` im Tab **Tools** auf. Der Inspector zeigt dir das Ergebnis: nur den Rückgabewert. Die Zeile

```text
Searching for 'dune'
```

ging nach Standard Error: ins Terminal, nicht auf die Leitung.

!!! info
    Wenn du eigentlich *Tracing* willst (jeden Request, wie lange er gedauert hat, ob er fehlgeschlagen ist),
    willst du keine Log-Zeilen, sondern Spans. Dein Server sendet sie bereits: Das SDK zeichnet ohne weitere
    Konfiguration jede Nachricht mit OpenTelemetry auf. Siehe **[OpenTelemetry](../run/opentelemetry.md)**.

## Zusammenfassung {#recap}

* Die Logging-Capability des MCP-Protokolls ist mit der Spezifikation 2026-07-28 veraltet und wird nicht ersetzt. Bau nicht darauf auf.
* `logger = logging.getLogger(__name__)` auf Modulebene, `logger.info(...)` im Tool. Das ist das ganze Muster.
* Log-Ausgaben erreichen das Modell nie. Nur der Wert, den du mit `return` zurückgibst.
* Standard Error gehört dir; stdout gehört dem Protokoll. Das SDK leitet geflushtes, verirrtes stdout während des Betriebs nach stderr um, aber ein ungeflushtes `print()` kann beim Beenden trotzdem auf die Leitung gelangen, und umgeleitete Zeilen kommen ohne Kennzeichnung an. Nimm `logging`, dessen Handler jeden Eintrag flusht.
* `MCPServer(..., log_level="DEBUG")` setzt das Level, und eine Logging-Konfiguration, die du vorher angelegt hast, bleibt unangetastet.

Wie du verbundenen Clients mitteilst, dass sich auf deinem Server etwas geändert hat (die Tool-Liste, eine Ressource), steht in **[Abonnements](subscriptions.md)**.
