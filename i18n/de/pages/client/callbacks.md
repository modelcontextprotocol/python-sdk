---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# Client-Callbacks {#client-callbacks}

Fast jeder Request in MCP läuft in eine Richtung: vom Client zum Server.

Ein Server kann aber auch den **Client** um etwas bitten: der Person am Host eine Frage zu stellen, ihr Modell per Sampling zu nutzen, ihre Arbeitsverzeichnisse aufzulisten. Diese Requests beantwortest du, indem du `Client(...)` **Callbacks** übergibst.

## Ein Server, der fragt {#a-server-that-asks}

Hier ist ein Server, dessen Tool allein nicht fertig werden kann:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` sendet einen `elicitation/create`-Request **an den Client** und wartet.
* Das Tool kehrt erst zurück, wenn jemand (eine Person in einem Formular oder dein Code) einen `name` liefert.

Das ist die Server-Hälfte, und die gehört der Seite **[Elicitation](../handlers/elicitation.md)** (Elicitation: Rückfrage bei der Person am Host). Diese Seite hier ist das andere Ende der Leitung.

## Der Elicitation-Callback {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* Ein Elicitation-Callback ist `async (context, params) -> ElicitResult`.
* `params.message` ist die Frage. `params.requested_schema` ist das JSON-Schema der Antwort, die der Server haben will. Ein echter Client rendert daraus ein Formular; dieser hier füllt es automatisch aus.
* Du gibst `ElicitResult(action="accept", content={...})` zurück, oder `action="decline"`, oder `action="cancel"`. Die einzige andere Möglichkeit ist `ErrorData(...)`: Das weist den Request zurück und lässt den gesamten Aufruf fehlschlagen.
* `context` ist ein `ClientRequestContext`: die laufende `session`, die `request_id` des Servers und alles, was er an `meta` angehängt hat.

!!! tip
    `params` ist eine Union der beiden Elicitation-Modi. Hier ist `params.mode` gleich `"form"`; ein `"url"`-Request
    trägt `params.url` statt eines Schemas. Ein Callback behandelt beide; verzweige anhand von `params.mode`.
    **[Elicitation](../handlers/elicitation.md)** zeigt das vollständige Muster.

### Ausprobieren {#try-it}

Rufe `issue_card` auf und beobachte beide Enden.

Dein Callback erhält die Frage des Servers, bereits geparst:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

Er antwortet, `ctx.elicit(...)` läuft im Tool weiter, und das Tool wird fertig:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

Ein `tools/call` von dir, ein `elicitation/create` zurück vom Server, beantwortet von deiner Funktion – alles innerhalb eines einzigen Tool-Aufrufs.

!!! info
    `mode="legacy"` im `Client(...)`-Aufruf leistet echte Arbeit. Standardmäßig handelt `Client(...)` den modernen
    Protokollpfad aus, und dieser Pfad hat keinen Rückkanal (back-channel) für Requests vom Server an den Client: `ctx.elicit`
    schlägt fehl, bevor dein Callback überhaupt läuft. Das entscheidet nicht der Transport, sondern das ausgehandelte
    Protokoll – in-memory genauso wie über eine URL. Setze `mode="legacy"` fest, wann immer dein Client
    einen solchen Request beantworten muss; jeder Test hinter dieser Seite tut das. Alles Weitere steht in **[Protokollversionen](../protocol-versions.md)**.

    In einer 2026-07-28-Session ist der Callback nicht tot, er wird nur anders gespeist: Gibt ein Tool ein
    `InputRequiredResult` zurück, das einen `ElicitRequest` trägt, leitet `Client` diesen Eintrag an denselben
    `elicitation_callback` weiter und wiederholt den Aufruf für dich. Dieser Ablauf heißt **[Multi-Roundtrip-Requests](../handlers/multi-round-trip.md)** (multi-round-trip requests).

## Ein Callback ist eine Capability {#a-callback-is-a-capability}

Du hast dem Server nie gesagt, dass dein Client Elicitation-Requests beantworten kann. Das SDK hat es getan.

Wenn sich ein Client verbindet, deklariert er seine `capabilities`, das Spiegelbild derer des Servers. Dieses Objekt schreibst du nicht. **Einen Callback zu registrieren ist die Deklaration.**

| du übergibst | der Client deklariert |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| keinen davon | `{}` |

Die Sampling-Sub-Capabilities sind die eine Verfeinerung: Übergib `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` zusammen mit `sampling_callback`, wenn dein Sampler die Parameter `tools` / `tool_choice` verarbeitet. Server müssen `sampling.tools` deklariert sehen, bevor sie diese senden dürfen.

`logging_callback` und `message_handler` stehen nicht in der Tabelle. Sie verarbeiten Benachrichtigungen, und Benachrichtigungen brauchen keine Capability.

Der Server liest die Deklaration mit `ctx.session.check_client_capability(...)` zurück. Füge ein Tool hinzu, das genau das tut:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

Verbinde dich nur mit `elicitation_callback` und rufe es auf:

```python
result.structured_content  # {'result': ['elicitation']}
```

Übergibst du alle drei Callbacks, bekommst du `['elicitation', 'sampling', 'roots']`. Übergibst du keinen, bekommst du `[]`.

!!! check
    Jetzt mach es absichtlich falsch: Verbinde dich **ohne** `elicitation_callback` und rufe `issue_card` trotzdem auf.

    Der `elicitation/create`-Request des Servers erreicht deinen Client trotzdem, und das SDK beantwortet ihn für
    dich – mit einem Fehler, weil du nie gesagt hast, dass du ihn verarbeiten kannst. Dieser Fehler lässt den gesamten Aufruf scheitern.
    `call_tool` gibt kein `is_error`-Ergebnis zurück; es wirft eine Exception:

    ```text
    MCPError: Elicitation not supported
    ```

    Das ist ein Protokollfehler (`-32600`, *invalid request*), kein Tool-Fehler: Es gibt nichts, was
    das Modell lesen und erneut versuchen könnte. Deshalb lohnt sich `client_features`: Ein Server,
    der sich gut benimmt, prüft, bevor er fragt.

## Das veraltete Paar {#the-deprecated-pair}

`sampling_callback` beantwortet `sampling/createMessage`: Der Server bittet *dein* Modell um eine Completion. `list_roots_callback` beantwortet `roots/list`: Der Server fragt, in welchen Verzeichnissen er arbeiten darf.

Beide funktionieren. Beide folgen der Regel oben. Und beide bedienen RPCs, die die **Spezifikation 2026-07-28 entfernt**: Ein moderner Server ruft nicht mitten im Request in deinen Client zurück, sondern reicht dir den Request als Teil des Tool-Ergebnisses zurück (**[Multi-Roundtrip-Requests](../handlers/multi-round-trip.md)**). Die Callbacks selbst sind nicht tot. Trägt ein `InputRequiredResult` einen `CreateMessageRequest` oder einen `ListRootsRequest`, leitet die Auto-Schleife von `Client` ihn an denselben `sampling_callback` oder `list_roots_callback` weiter, den du hier registriert hast. Die vollständige Liste steht in **[Veraltete Features](../deprecated.md)**.

Du brauchst die Callbacks weiterhin, um mit Servern zu sprechen, die noch nicht umgestiegen sind. Die Signaturen:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* Ein Sampling-Callback erhält die vollständigen `CreateMessageRequestParams` (`messages`, `model_preferences`, `max_tokens`) und gibt ein `CreateMessageResult` zurück. *Du* betreibst das Modell, ganz wie du willst; das SDK transportiert nur den Request.
* Ein Roots-Callback nimmt überhaupt keine Parameter entgegen und gibt ein `ListRootsResult` zurück.
* Beide dürfen stattdessen `ErrorData(...)` zurückgeben, um abzulehnen.

Übergib sie an `Client(...)` genau wie `elicitation_callback`.

## Die Benachrichtigungs-Callbacks {#the-notification-callbacks}

Zwei weitere. Keiner deklariert etwas.

`logging_callback` erhält die `notifications/message`, die ein Server sendet, als `LoggingMessageNotificationParams` (`level`, `logger`, `data`). Das Protokoll-Logging selbst ist mit der Spezifikation 2026-07-28 veraltet (was du stattdessen tust, steht in **[Logging](../handlers/logging.md)**), dieser Callback existiert also für die Server, die es noch ausgeben. Auf einer Verbindung der 2026er-Generation bringt dir der Callback allein nichts, denn 2026er-Server senden Log-Nachrichten nur an Requests, die sich dafür anmelden: Übergib `log_level="info"` (oder ein anderes Level) an `Client(...)`, um dieses Opt-in jedem Request aufzuprägen und dieses Level und alles darüber zu empfangen. Server vor 2026 ignorieren das und behalten ihr `logging/setLevel`-Verhalten.

`message_handler` ist das Sammelbecken: Jede Server-Benachrichtigung, die die Session nach oben reicht, landet dort (zusätzlich zu ihrem spezifischen Callback), und auf einem Stream-gestützten Transport auch jede `Exception` auf Transportebene. Zwei kommen nie an: `notifications/cancelled` wendet das SDK an, statt sie nach oben zu reichen, und eine Abonnement-Bestätigung für einen laufenden `listen()`-Stream verbraucht dieser Stream selbst. Annotiere den Parameter mit `IncomingMessage` (`ServerNotification | Exception`, exportiert aus `mcp.client`). Das eine Muster, das du kennen solltest, ist `if isinstance(message, Exception): raise message`, damit eine unterbrochene Verbindung laut fehlschlägt, statt still zu verschwinden.

## Zusammenfassung {#recap}

* Ein Server kann Requests an den Client senden. Du beantwortest sie mit Callbacks, die du `Client(...)` übergibst.
* Der Elicitation-Callback ist der aktuelle: `async (context, params) -> ElicitResult`, eine Funktion für Formular- und URL-Modus.
* **Einen Callback zu registrieren heißt, die Capability zu deklarieren.** Ohne ihn weist das SDK den Request des Servers in deinem Namen zurück, und der gesamte Aufruf schlägt mit `MCPError` fehl.
* Ein Server findet das vor dem Fragen mit `ctx.session.check_client_capability(...)` heraus.
* `sampling_callback` und `list_roots_callback` funktionieren genauso, bedienen aber veraltete Features; moderne Server verwenden stattdessen Multi-Roundtrip-Requests.
* `logging_callback` und `message_handler` empfangen Benachrichtigungen. Sie deklarieren nichts.

Das erste Argument von `Client(...)` ist ein Transport-Objekt. **[Client-Transporte](transports.md)** behandelt jede Art davon.
