---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# Abhängigkeiten {#dependencies}

Die Argumente eines Tools kommen vom Modell. Manche Werte sollten das nie: ein Preis, den du in deinen eigenen Datensätzen nachschlägst, eine Bestätigung, die nur ein Mensch geben kann, alles, bei dem das Modell danebenliegen könnte, wenn es den Wert erfindet.

**Abhängigkeiten** sind Parameter, die deine eigenen Funktionen füllen. Du annotierst den Parameter, nennst die Funktion, und das SDK ruft sie auf, bevor dein Tool läuft.

## Eine Abhängigkeit deklarieren {#declare-one}

Umschließe den Typ des Parameters mit `Annotated[...]` und füge `Resolve(fn)` hinzu:

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` ist ein **Resolver**: eine gewöhnliche Funktion, die das SDK vor `reserve_book` ausführt und deren Rückgabewert zum Argument `stock` wird.
* Sein Parameter `title` ist das `title`-Argument des Tools selbst, zugeordnet **über den Namen**. Der Resolver sieht genau den validierten Wert, den auch der Tool-Rumpf sehen wird.
* Der Tool-Rumpf beginnt mit einem `Stock`, der bereits existiert. Kein Nachschlage-Code im Tool, keine „Was, wenn er fehlt“-Vorrede.

!!! info
    Wenn du FastAPI kennst: Das ist `Depends`. Derselbe Kniff, derselbe Grund: Die Funktion
    deklariert, was sie braucht, das Framework liefert es, und die Verdrahtung steckt in der Typannotation.

### Für das Modell unsichtbar {#invisible-to-the-model}

Das ist das Eingabeschema, das `tools/list` für `reserve_book` meldet:

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

Eine einzige Property. Wie der `Context` in **[Der Context](context.md)** ist ein aufgelöster Parameter ein Vertrag zwischen dir und dem SDK: `stock` steht nicht im Schema, das Modell erfährt nie davon, und ein Client, der trotzdem einen `stock`-Wert schickt, wird ignoriert. Der Wert des Resolvers ist der einzige, den dein Tool empfangen kann.

Dieser letzte Teil ist der Kern. Ein Parameter, den das Modell nicht liefern kann, ist ein Parameter, bei dem das Modell nichts falsch machen kann.

### Ausprobieren {#try-it}

Starte den Server mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Das Formular für `reserve_book` hat ein einziges Feld `title`. `stock` taucht nirgends auf. Rufe es mit `Dune` auf:

```text
Reserved 'Dune' (6 copies left).
```

Der Tool-Rumpf hat nichts nachgeschlagen: `check_stock` lief zuerst, und der zurückgegebene `Stock` kam als Argument an. Probiere `Neuromancer`, und derselbe Resolver reicht dem Tool eine Null.

!!! tip
    Du kannst `check_stock(title)` auch einfach im Tool-Rumpf aufrufen. Deklariere es als Abhängigkeit,
    wenn der Wert mehr verdient als einen Hilfsaufruf: Jedes Tool, das den Bestand braucht, deklariert
    denselben Parameter, und das SDK führt den Resolver höchstens einmal pro Aufruf aus, egal wie viele
    ihn deklarieren. Die nächsten Abschnitte liefern den Rest: Resolver, die voneinander abhängen, und
    Resolver, die die Person am Host fragen.

## Abhängigkeiten von Abhängigkeiten {#dependencies-of-dependencies}

Ein Resolver kann eigene Abhängigkeiten deklarieren, mit derselben Annotation:

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` hängt von `check_stock` ab. Das SDK führt den Graphen der Reihe nach aus: erst der Bestand, dann die Schätzung, dann das Tool.
* Sowohl `stock` als auch `delivery` brauchen letztlich `check_stock`, aber es läuft **einmal pro Aufruf**. Eine Bestandsabfrage, zwei Konsumenten.
* Es gibt nichts zu registrieren. Die Annotationen *sind* der Graph.

!!! check
    Glaube das „einmal pro Aufruf“ nicht einfach. Setze ein `print` in `check_stock` und rufe
    `order_book` aus dem Inspector auf: eine Zeile pro Aufruf. Zwei Konsumenten, eine Abfrage.

Das SDK analysiert den Graphen, wenn das Tool registriert wird, nicht wenn es aufgerufen wird. Ein Parameter, den es nicht einordnen kann – kein `Context`, kein `Resolve(...)`, nicht der Name eines Tool-Arguments –, und ein Zyklus von Resolvern lösen beide beim Start `InvalidSignature` aus. Dein Server scheitert, bevor sich je ein Client verbindet, und der Fehler nennt den betreffenden Parameter oder Resolver.

Die Parameter eines Resolvers werden genau wie die eines Tools aufgelöst: ein weiteres `Resolve(...)`, die eigenen Argumente des Tools über den Namen oder der `Context` – `ctx.headers`, das Lifespan-Objekt, alles davon.

!!! warning
    Auf HTTP-Transporten enthält der `Context` auch `ctx.headers`. Header sind **vom Client gelieferte
    Eingaben**, wie jedes Tool-Argument: in Ordnung für eine Locale oder ein Feature-Flag, nie für eine
    Identität. Wer aufruft, bestimmt deine Autorisierungsschicht (**[Autorisierung](../run/authorization.md)**),
    nicht ein Header, der sich beliebig setzen lässt.

!!! tip
    *Einmal pro Aufruf* heißt genau das: Der nächste `tools/call` führt `check_stock` erneut aus. Eine
    Ressource, die einen Request überdauern soll – ein Datenbank-Pool, ein HTTP-Client –, gehört in den
    **[Lifespan](lifespan.md)**, und ein Resolver erreicht sie über `ctx.request_context.lifespan_context`.

## Fragen, wenn es sein muss {#ask-when-you-must}

Ein Resolver muss die Antwort nicht kennen. Er kann `Elicit(message, Model)` zurückgeben, und das SDK fragt die Person am Host – die Maschinerie der **[Elicitation](elicitation.md)** (Rückfrage bei der Person am Host), für dich ausgeführt:

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* Auf Lager: `confirm_backorder` gibt direkt ein `Backorder` zurück. **Keine Frage, kein Roundtrip.** Die Person wird nur unterbrochen, wenn ihre Antwort zählt.
* Nicht auf Lager: Das SDK sendet die Elicitation, validiert die Antwort gegen `Backorder` und injiziert sie. Dein Resolver berührt das Protokoll nie.
* Das Tool liest `backorder.confirm` wie jedes andere Argument. **Nein** zu antworten ist trotzdem eine Antwort: Die Elicitation wird mit `confirm=False` akzeptiert, das Tool läuft, und es wird keine Bestellung aufgegeben. Das Fragen ist zur Vorbedingung geworden, nicht zu Hilfscode im Tool-Rumpf.

Und wenn die Person gar nicht antwortet – die Frage ablehnt oder abbricht?

!!! check
    Führe `order_book` für `Neuromancer` aus und lehne die Frage ab. Mit der Annotation
    `Annotated[Backorder, Resolve(...)]` läuft der Tool-Rumpf nie; der Aufruf scheitert mit einem
    Fehlerergebnis, das das Modell lesen kann:

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

Das ist der richtige Standardwert für eine Vorbedingung: keine Antwort, keine Bestellung. Wenn Ablehnen ein Ergebnis ist, das dein Tool behandeln will – die Nachbestellung überspringen, aber trotzdem einen anderen Titel vorschlagen –, annotiere stattdessen `ElicitationResult[Backorder]`, und das Tool erhält das vollständige Ergebnis aus accept/decline/cancel, nach dem es verzweigen kann. **[Elicitation](elicitation.md)** zeigt diese Form und alles Weitere zum Fragen: die Schema-Regeln, die drei Antworten, die Client-Seite des Gesprächs.

!!! info
    Das Framework wählt den Transport der Frage anhand der ausgehandelten Protokollversion; der Code
    oben ist in beiden Fällen identisch. Ab **2026-07-28** reist die Frage innerhalb eines
    Multi-Roundtrip-`tools/call` (multi-round-trip) – der Server gibt sie zurück, der
    `elicitation_callback` des Clients beantwortet sie, und der `Client` wiederholt den Aufruf für dich
    (**[Multi-Roundtrip-Requests](multi-round-trip.md)**). Bei **2025-11-25** und früher ist es ein
    synchroner Elicitation-Request mitten im Aufruf. Jede Frage wird genau einmal pro Aufruf gestellt –
    eine Garantie über die Frage, nicht über den Resolver. In der Multi-Roundtrip-Form kann jeder
    Resolver erneut laufen, sobald der Aufruf nach einer Frage fortgesetzt wird; Code vor einem
    `return Elicit(...)` läuft also in jeder dieser Runden. Die aufgezeichnete Antwort erfüllt dann die
    wiederholte Frage, ohne die Person erneut zu fragen. Eine aufgezeichnete Antwort wird überhaupt nur
    herangezogen, wenn der Resolver fragt; ein Resolver, der antwortet, *ohne* zu fragen, wie
    `check_stock`, liefert immer seinen selbst berechneten Wert. Weil jede Antwort ihrer Frage
    zugeordnet wird, muss ein fragender Resolver seine Frage deterministisch aus den Argumenten des
    Tools und früheren Antworten ableiten. Ein pro Aufruf erzeugter Wert (eine ID aus
    `default_factory`, ein Zeitstempel) wird in jeder Runde neu abgeleitet und darf nicht in einer
    Frage vorkommen, an die sich die Antwort binden soll. Eine Frage aus solch flüchtigen Daten lässt
    jede aufgezeichnete Antwort veraltet aussehen, sodass der Server sie in jeder Runde erneut stellt,
    bis das Rundenlimit des Clients den Aufruf beendet.

## Den Client fragen, nicht die Person {#ask-the-client-not-the-user}

Elicitation ist eine von drei Fragen, die ein Resolver stellen kann, und der Multi-Roundtrip-Ablauf lässt keine weiteren zu. Die beiden anderen gehen an den **Client** statt an die Person: Gib `Sample(...)` zurück, um einen LLM-Aufruf über den Client auszuführen (ein `sampling/createMessage`-Request), oder `ListRoots()`, um die aktuellen Roots (freigegebene Arbeitsverzeichnisse) des Clients abzurufen. Keine von beiden hat ein Ergebnis aus accept/decline; der Konsument annotiert direkt den Ergebnistyp, `CreateMessageResult` (`CreateMessageResultWithTools`, wenn der Request `tools` oder `tool_choice` trägt) oder `ListRootsResult`:

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* Das Framework leitet sie genau wie `Elicit`: innerhalb des Multi-Roundtrip-`tools/call` bei **2026-07-28**, über den eigenständigen Server-zu-Client-Request bei **2025-11-25**. Eine nicht deklarierte Capability verweigert den Aufruf mit einem Protokollfehler `-32021` (`sampling`, `roots`, `elicitation` im Formularmodus; `sampling.tools`, wenn der Request `tools` oder `tool_choice` trägt).
* Alles, was der Info-Kasten oben über Fragen sagt, gilt unverändert: Ein `Sample`-Request wird seinem aufgezeichneten Ergebnis über seine exakte Darstellung zugeordnet, baue ihn also deterministisch aus den Argumenten des Tools und früheren Antworten; der Client zahlt dann für den LLM-Aufruf einmal pro Tool-Aufruf, nicht einmal pro Runde. Das aufgezeichnete Ergebnis reist für den Rest des Aufrufs in `request_state` mit, sodass eine sehr große Completion jeden verbleibenden Roundtrip schwerer macht.
* Die eigenständigen *Features* Sampling und Roots sind ab 2026-07-28 veraltet (SEP-2577). Neue Server, die das Modell des Clients brauchen, fragen über diesen Träger; Server, die es nicht brauchen, sollten direkt einen LLM-Anbieter anbinden. Andere `include_context`-Werte als `"none"` sind selbst veraltet; vermeide sie.

## Zusammenfassung {#recap}

* `Annotated[T, Resolve(fn)]` an einem Tool-Parameter: Das SDK führt `fn` aus und injiziert den Rückgabewert.
* Ein aufgelöster Parameter ist für das Modell unsichtbar, und ein Client kann ihn nicht liefern. Werte, die das Modell nicht erfinden darf – Preise, Identitäten, Berechtigungen –, gehören hierher.
* Die Parameter eines Resolvers werden genauso aufgelöst: der `Context`, ein weiteres `Resolve(...)` oder ein Tool-Argument über den Namen. Der Graph führt jeden Resolver höchstens einmal pro Runde aus, egal wie viele Konsumenten er hat; jede Frage wird genau einmal gestellt, und jeder Resolver kann erneut laufen, wenn ein Aufruf nach einer Frage fortgesetzt wird.
* Fehlerhafte Graphen scheitern bei der Registrierung mit `InvalidSignature`, nicht mitten im Aufruf.
* Gib `Elicit(message, Model)` zurück, um die Person zu fragen – nur, wenn es sein muss. Unverpackte Annotationen brechen bei Ablehnung ab; mit `ElicitationResult[T]` kann das Tool verzweigen.
* Gib `Sample(...)` oder `ListRoots()` zurück, um den Client nach einer Antwort des Modells oder der Liste der Roots zu fragen; das reine Ergebnis wird injiziert.

Den Zustand, den dein Server einmal beim Start aufbaut, und wie ein Handler ihn erreicht, behandelt die Seite **[Lifespan](lifespan.md)**.
