---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# Sampling und Roots {#sampling-and-roots}

Ein Handler kann den verbundenen Client um zwei weitere Dinge bitten: eine Completion vom eigenen Modell des Clients (**Sampling**) und die Arbeitsverzeichnisse des Clients (**Roots**, freigegebene Arbeitsverzeichnisse).

Beides funktioniert weiterhin, auf jeder Protokollversion, die das SDK spricht. Lies aber die Warnung, bevor du dein Design darauf aufbaust:

!!! warning "Veraltet seit der Spezifikation 2026-07-28"
    Sampling und Roots gelten seit `2026-07-28` als veraltet ([SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)). Sie bleiben voll funktionsfähig und stehen noch mindestens zwölf Monate in der Spezifikation, bevor sie entfernt werden dürfen, aber neue Implementierungen sollten nicht mehr darauf aufbauen. Die empfohlenen Migrationen: Binde statt Sampling direkt die API deines LLM-Anbieters an, und übergib Verzeichnisse statt über Roots per Tool-Parameter, Ressourcen-URI oder Serverkonfiguration. Die SDK-weite Liste steht in **[Veraltete Features](../deprecated.md)**.

## Sampling: das Modell des Clients ausleihen {#sampling-borrow-the-clients-model}

Ein Resolver gibt `Sample(...)` zurück, und das Tool erhält die Completion – über denselben Abhängigkeitsmechanismus, der in **[Abhängigkeiten](dependencies.md)** `Elicit` ausführt:

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` spiegelt die Parameter von `sampling/createMessage` wider. Der injizierte Wert ist das `CreateMessageResult` des Clients; übergibst du `tools` oder `tool_choice`, wird daraus stattdessen ein `CreateMessageResultWithTools`.
* Der Client muss die Capability `sampling` deklariert haben (`sampling.tools`, wenn du `tools` oder `tool_choice` übergibst). Hat er das nicht, schlägt der Aufruf mit einem Protokollfehler `-32021` fehl, statt einen Request zu senden, den der Client nicht verarbeiten kann. Eine Session aus der Zeit vor 2026 ohne Rückkanal (back-channel) schlägt mit ihrem üblichen No-Back-Channel-Fehler fehl, weil es nichts gibt, worüber gesendet werden könnte.
* Bei `2026-07-28` wird der Request innerhalb des Multi-Roundtrip-Ablaufs zugestellt (**[Multi-Roundtrip-Requests (multi-round-trip requests)](multi-round-trip.md)**); bei `2025-11-25` ist er ein eigenständiger Request an den Client. Der Code ist in beiden Fällen derselbe, beachte aber die Multi-Roundtrip-Regel: Der Request muss in jeder Wiederholungsrunde identisch aussehen. Baue ihn deshalb nur aus den Argumenten des Tools und anderen stabilen Daten.
* Lass `include_context` unangetastet: Andere Werte als `"none"` sind selbst veraltet (SEP-2596) und brauchen eine Capability, die fast kein Client deklariert.

## Roots: Wohin damit? {#roots-where-should-this-go}

Roots sind die Verzeichnisse, auf denen der Server laut Client arbeiten darf. Sie sind ein informativer Hinweis, kein Mechanismus zur Zugriffskontrolle. Ein Resolver gibt `ListRoots()` zurück:

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* Das injizierte `ListRootsResult` enthält eine Liste von `Root`-Objekten: jeweils einen `file://`-URI und einen optionalen Anzeigenamen.
* Die Hürde ist dieselbe wie beim Sampling: Ohne deklarierte Capability `roots` schlägt der Aufruf mit `-32021` fehl, statt den Request zu senden.

Auf der anderen Seite der Leitung beantwortet der Client beide Requests mit den Callbacks, die er ohnehin schon hat: `sampling_callback` und `list_roots_callback`, beschrieben in **[Client-Callbacks](../client/callbacks.md)**.

## Auf Verbindungen der 2025er-Generation {#on-2025-era-connections}

`ctx.session.create_message(...)` und `ctx.session.list_roots()` gibt es weiterhin für Code, der die Session direkt ansteuert. Sie funktionieren nur dort, wo ein Rückkanal existiert (nicht zustandslose Verbindungen der 2025er-Generation), und ihr Aufruf löst eine Deprecation-Warnung aus. Die Resolver-Marker oben sind die unterstützte Form: Sie wählen die Zustellung anhand der ausgehandelten Version und warnen nicht.

## Zusammenfassung {#recap}

* Gib `Sample(...)` oder `ListRoots()` aus einem Resolver zurück; das Tool erhält das `CreateMessageResult` oder `ListRootsResult` wie jede andere Abhängigkeit.
* Der Client muss die passende Capability deklarieren, sonst schlägt der Aufruf mit `-32021` fehl, statt dass ein Request gesendet wird.
* Beide Features sind bei `2026-07-28` veraltet: vorerst voll funktionsfähig, aber falsch für neue Designs. Bevorzuge Anbieter-APIs gegenüber Sampling und explizite Parameter gegenüber Roots.

Wie ein langsames Tool seinen Fortschritt meldet: **[Fortschritt](progress.md)**.
