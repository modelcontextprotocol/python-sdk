---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# Protokollversionen {#protocol-versions}

MCP hat zwei Generationen.

Server, die vor 2026-07-28 veröffentlicht wurden, eröffnen jede Verbindung mit dem **`initialize`-Handshake**: Der Client schlägt eine Version vor, der Server hält dagegen, der Client bestätigt – alles vor dem ersten nützlichen Request. Server auf Stand **2026-07-28** lassen den Handshake weg. Der Client sendet eine einzige **`server/discover`**-Sondierung, und der Server beantwortet sie mit allem in einem einzigen Ergebnis.

Darum musst du dich fast nie kümmern, denn `Client` handelt das für dich aus. Diese Seite behandelt das eine Konstruktorargument, das es steuert, `mode=`, und die drei Fälle, in denen du es änderst.

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

Du hast `mode` nicht übergeben, also bekommst du den Standardwert: `"auto"`. Beim Eintritt in `async with` geht eine einzige `server/discover`-Sondierung in der neuesten Version raus, die dieses SDK spricht. Dann:

* Ein **moderner Server** beantwortet sie. Der Client übernimmt das Ergebnis. Ein Roundtrip, fertig.
* Ein **älterer Server** hat noch nie von `server/discover` gehört und gibt einen Fehler zurück. Der Client fällt auf den klassischen `initialize`-Handshake zurück und nimmt, was dieser aushandelt.

So oder so bist du am Ende verbunden, und `client.protocol_version` sagt dir, welcher Weg es war:

```text
2026-07-28
```

Das ist das ganze Feature. Ein `Client`, Server jeder Generation, keine Verzweigung in deinem Code.

!!! info
    `MCPServer` beantwortet `server/discover` auf jedem Transport – In-Memory, stdio, Streamable
    HTTP –, sodass `auto` gegen deinen eigenen Server immer bei `2026-07-28` landet. Der Fallback
    greift nur gegen einen echten Server von vor 2026, und genau dann willst du ihn auch.

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` sondiert nie. Es führt den `initialize`-Handshake aus – dieselbe Verbindung, die ein Client von vor 2026 öffnet.

```text
2025-11-25
```

Derselbe Server. Er spricht `2026-07-28` einwandfrei; du hast dem Client gesagt, nicht danach zu fragen.

Das willst du für die **Push-Features**.

Ein vom Server initiierter Request bedeutet, dass der Server *dich* aufruft: `ctx.elicit(...)` legt der Person am Host ein Formular vor, Sampling bittet dein Modell mitten in einem Tool-Aufruf um eine Completion. Diesen Kanal gibt es nur in einer Session der Handshake-Generation.

Bei 2026-07-28 ist er weg. Der Server *gibt* seine Fragen *zurück*, und du wiederholst den Aufruf mit den Antworten – siehe **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)** (multi-round-trip requests).

`mode="auto"` gibt dir nur dann einen Handshake, wenn der Server für alles andere zu alt ist. `mode="legacy"` garantiert einen. Greif dazu, wann immer du `Client(...)` einen `sampling_callback`, einen `elicitation_callback`, der als Request ausgelöst werden soll, oder einen `message_handler` übergibst. **[Client-Callbacks](client/callbacks.md)** geht jeden davon durch.

## Eine Version festschreiben {#pinning-a-version}

`mode` akzeptiert auch den String einer modernen Protokollversion. Heute ist diese Menge genau `["2026-07-28"]`.

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

Eine festgeschriebene Version sendet **nichts**. Keine Sondierung, kein Handshake. Der Client übernimmt `2026-07-28` lokal, und die Verbindung steht in dem Moment, in dem `async with` zurückkehrt.

Eine festgeschriebene Version ist ein Versprechen, das *du* gibst: Du weißt bereits, dass der Server diese Version spricht. Der Client prüft das nicht.

!!! check
    Festschreiben ist keine Erkennung. Gib `client.server_info` aus, und der Preis steht direkt da:

    ```text
    None
    ```

    Der Client hat den Server nie gefragt, wer er ist, also ist `server_info` `None`. Bei `client.server_capabilities`
    dasselbe: Jede Capability ist `None`. Tool-Aufrufe funktionieren weiterhin (das Protokoll braucht nichts davon);
    Code, der `server_capabilities` liest, um zu entscheiden, was er anbietet, funktioniert nicht.

    Der nächste Abschnitt ist die Lösung.

Nur moderne Versionen lassen sich festschreiben. Ein String der Handshake-Generation wird schon beim Konstruieren abgelehnt, vor jedem I/O, und der Fehler sagt dir, was du stattdessen schreiben sollst:

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## Mit `prior_discover` neu verbinden {#reconnecting-with-prior_discover}

Die Sondierung ist billig, aber sie bleibt ein Roundtrip, den du bei jedem Neuverbinden bezahlst, und die Antwort ändert sich fast nie.

Also heb sie auf. Nach einer `auto`-Verbindung enthält `client.session.discover_result` genau das `DiscoverResult`, das der Server gesendet hat: seine `supported_versions`, seine `capabilities`, seine `instructions` und die Identität, die der Server in das `_meta` des Ergebnisses gestempelt hat. Gib es beim nächsten Mal als `prior_discover=` zurück:

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

Die zweite Verbindung hat **keinen einzigen** Roundtrip für die Aushandlung gebraucht und weiß trotzdem genau, mit wem sie spricht. Das ist der festgeschriebene Modus, richtig gemacht: `mode=` nennt die Version, `prior_discover=` liefert die Identität. ✨

`DiscoverResult` ist ein Pydantic-Modell. `saved.model_dump_json()` wandert in eine Datei oder einen Cache; `DiscoverResult.model_validate_json(...)` holt es im nächsten Prozess zurück.

!!! tip
    `prior_discover=` bewirkt nur dann etwas, wenn `mode` eine festgeschriebene Version ist. Unter `"auto"`
    sondiert der Client den Server ohnehin, und unter `"legacy"` wird es ignoriert.

## Die vier Modi {#the-four-modes}

| Du schreibst | Traffic für die Aushandlung | Du bekommst |
| --- | --- | --- |
| `Client(target)` | eine `server/discover`-Sondierung; der `initialize`-Handshake, falls sie fehlschlägt | die neueste Version, die beide Seiten sprechen, egal welcher Generation |
| `Client(target, mode="legacy")` | der `initialize`-Handshake | eine Version der Handshake-Generation; vom Server initiierte Requests funktionieren |
| `Client(target, mode="2026-07-28")` | keiner | diese Version, festgeschrieben, mit `server_info` als `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | keiner | diese Version, festgeschrieben, *und* die Identität, die du letztes Mal gespeichert hast |

## Zusammenfassung {#recap}

* MCP hat eine Handshake-Generation (bis `2025-11-25`, der `initialize`-Handshake) und eine moderne Generation (`2026-07-28`, `server/discover`). `Client` überbrückt beide.
* `mode="auto"` ist der Standardwert: sondieren, zurückfallen. Lass es in Ruhe, es sei denn, eine der anderen drei Zeilen beschreibt dich.
* `client.protocol_version` ist immer die Antwort auf „Was habe ich bekommen?“.
* `mode="legacy"` erzwingt den Handshake. Das brauchst du für vom Server initiierte Requests: Sampling, Push-Elicitation (Rückfrage bei der Person am Host), `message_handler`.
* Eine festgeschriebene Version (`mode="2026-07-28"`) sendet überhaupt keinen Traffic für die Aushandlung – um den Preis, dass `client.server_info` `None` ist.
* `prior_discover=` gleicht diesen Preis wieder aus: Speichere `client.session.discover_result`, verbinde dich damit neu, bekomm beides.

Eine moderne Verbindung hat keinen Push-Kanal – wie also stellt dir ein 2026er-Server mitten im Aufruf eine Frage? Er gibt sie zurück: **[Multi-Roundtrip-Requests](handlers/multi-round-trip.md)**.
