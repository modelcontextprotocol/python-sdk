---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# Elicitation {#elicitation}

Ein Tool, das mitten in seiner Arbeit steckt und dem eine Antwort fehlt, muss nicht scheitern.

Mit **Elicitation** (Rückfrage bei der Person am Host) kann es fragen. Mitten in einem Tool-Aufruf bekommt die Person eine Frage gestellt, und ihre Antwort landet wieder im selben Funktionsaufruf.

Es gibt zwei Modi:

* **Formular-Modus**: Du brauchst einen Wert (eine Bestätigung, ein Datum, eine Menge). Du beschreibst die Felder, der Client rendert das Formular.
* **URL-Modus**: Die Person muss woanders hin (ein OAuth-Zustimmungsbildschirm, eine Bezahlseite). Nichts von dem, was sie dort tut, läuft über das Protokoll.

Und es gibt zwei Wege zu fragen. Der Weg der Wahl ist ein **Resolver**: Du hängst die Frage an einen Parameter, und das SDK fragt – auf jeder Verbindung, egal welche Protokollgeneration der Client spricht. Der direkte Weg, `await ctx.elicit(...)`, ist ein Request vom *Server* an den *Client*, ein Kanal, den es nur für einen Client auf einer Legacy-Verbindung gibt (Spec-Version 2025-11-25 oder älter). Beide stehen auf dieser Seite; fang mit dem Resolver an.

## Mit einem Resolver fragen {#ask-with-a-resolver}

Eine Frage, die das ganze Tool blockiert – *bist du sicher? welches der drei passenden Konten?* – lässt sich aus dem Tool-Body in einen **Resolver** herausziehen, und das Framework stellt sie für dich.

Ein Parameter mit der Annotation `Annotated[T, Resolve(fn)]` wird befüllt, indem `fn` vor dem Tool-Body läuft. Der Resolver gibt den Wert direkt zurück, wenn er ihn schon kennt, oder gibt `Elicit(...)` zurück, damit das Framework fragt:

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` liest das eigene Argument `path` des Tools über den Namen aus, listet den Ordner auf und **fragt nur, wenn es sein muss** – ein leerer Ordner wird zu `Confirm(ok=True)` aufgelöst, ohne Roundtrip zum Client.
* `delete_folder` annotiert `ElicitationResult[Confirm]`, also injiziert das Framework das ganze Ergebnis, und das Tool behandelt per `match` jeden Fall: annehmen und bestätigen, annehmen, aber behalten (`ok=False`), ablehnen, abbrechen.
* Der Parameter `confirm` taucht nie im Input-Schema des Tools auf – der Client liefert `path`, der Resolver liefert `confirm`.

Annotiere stattdessen das unverpackte Modell (`Annotated[Confirm, Resolve(confirm_delete)]`), wenn das Tool nicht verzweigen muss: Beim Annehmen bekommt es das Modell, bei Ablehnen oder Abbrechen bricht der Aufruf mit einem Fehler ab.

Ein Resolver funktioniert auf **jeder** Verbindung. Einem Client auf einer Legacy-Verbindung schickt das SDK die Frage direkt; auf einer **2026-07-28**-Verbindung *gibt* das SDK die Frage aus dem Aufruf *zurück*, und der nächste Versuch des Clients trägt die Antwort. Dein Resolver merkt den Unterschied nie; was unter der Haube passiert, steht in **[Multi-Roundtrip-Requests](multi-round-trip.md)** (multi-round-trip requests).

Fragen ist nur eines von dem, was ein Resolver kann. Der allgemeine Mechanismus – Abhängigkeiten, die rechnen, ohne zu fragen, Abhängigkeiten von Abhängigkeiten, was das Modell liefern kann und was nicht – ist die Seite **[Abhängigkeiten](dependencies.md)**.

## Aus dem Tool heraus fragen {#ask-from-inside-the-tool}

Ein Tool kann auch mitten in seinem eigenen Body anhalten und fragen.

!!! warning
    `ctx.elicit()` und `ctx.elicit_url()` sind Requests vom *Server* an den *Client* – ein
    Kanal, den es nur für einen Client auf einer Legacy-Verbindung gibt (Spec-Version **2025-11-25**
    oder älter). Auf einer **2026-07-28**-Verbindung gibt es keine vom Server initiierten Requests,
    also schlagen diese Aufrufe fehl. Ein Resolver funktioniert auf beiden. Alles Weitere steht in
    **[Protokollversionen](../protocol-versions.md)**.

`await ctx.elicit()` nimmt eine Nachricht und ein Pydantic-Modell entgegen:

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* Der **`Context`**-Parameter gibt dir `ctx.elicit`; jedes Tool kann einen entgegennehmen. Dieses Objekt hat seine eigene Seite: **[Der Context](context.md)**.
* `AlternativeDate` ist das **Schema** der Antwort, die du haben willst.
* Das Tool ist `async def`. Das muss es sein: Es hält mittendrin an und wartet auf einen Menschen.
* An jedem anderen Datum gibt das Tool sofort zurück. Es fragt nur, wenn es muss.
* Das Datum, das die Person annimmt, läuft wieder durch `book_table` selbst. Eine Antwort ist Eingabe wie jede andere: Ist die Alternative ebenfalls ausgebucht, wird erneut gefragt statt blind bestätigt.

### Was der Client erhält {#what-the-client-receives}

Der Client bekommt deine Nachricht und daneben ein JSON Schema, das aus dem Modell generiert wird:

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

Dieses Schema ist das Formular. `Field(description=...)` ist die Beschriftung; ein Standardwert füllt das Eingabefeld vor und macht das Feld optional. Es ist dieselbe Pydantic-zu-JSON-Schema-Maschinerie, die **[Tools](../servers/tools.md)** für die Argumente eines Tools beschreibt.

!!! warning
    Ein Elicitation-Schema ist nicht so ausdrucksstark wie das Input-Schema eines Tools. Nur flache,
    primitive Felder: `str`, `int`, `float`, `bool` oder ein `Literal` aus Strings (daraus wird ein `enum`).
    Steckst du ein Modell in das Modell, löst `ctx.elicit` eine Exception aus, bevor irgendetwas an den Client geht:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    Du unterbrichst einen Menschen mitten in einer Aufgabe. Wenn die Antwort Verschachtelung braucht,
    hätte sie ein Argument des Tools sein sollen.

### Die drei Antworten {#the-three-answers}

`result.action` sagt dir, was die Person getan hat, und es gibt genau drei Möglichkeiten:

* `"accept"`: Sie hat das Formular abgeschickt. `result.data` ist eine `AlternativeDate`-Instanz, bereits validiert.
* `"decline"`: Sie hat Nein gesagt.
* `"cancel"`: Sie hat die Frage weggeklickt, ohne sich zu entscheiden.

`result.data` existiert nur bei `"accept"`, deshalb prüft das Beispiel zuerst `result.action`. Dein Type Checker erzwingt die Reihenfolge: Nach `result.action == "accept"` ist `result.data` ein `AlternativeDate`; davor gibt es gar kein `.data`.

Eine Absage ist kein Fehler. Das Tool entscheidet, was Ablehnen bedeutet (hier: keine Buchung), und antwortet dem Modell ganz normal.

!!! tip
    Die Antwort wird gegen dein Modell validiert, bevor dein Code sie sieht. Ein Client, der
    `"maybe"` für ein `bool` schickt, bringt deine Buchung nicht durcheinander: Der Aufruf schlägt mit einem
    Schema-Mismatch-Fehler fehl, dein `if` läuft nie.

## Die Person zu einer URL schicken {#send-the-user-to-a-url}

Manche Dinge dürfen nicht durch das Modell oder den Client laufen: Zugangsdaten, Kartennummern, OAuth-Zustimmung. Dafür fragst du nicht nach Daten; du bittest die Person, irgendwohin zu gehen:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` nimmt die Nachricht, die zu besuchende **URL** und eine `elicitation_id` deiner Wahl entgegen: einen beliebigen String, der diese Elicitation innerhalb deines Servers identifiziert.
* Das Ergebnis hat eine Action und sonst nichts. `"accept"` heißt, die Person hat zugestimmt, die URL zu öffnen, **nicht**, dass sie das, was auf der anderen Seite wartet, abgeschlossen hat.
* Die Zahlung läuft außerhalb des Protokolls, zwischen dem Browser der Person und deinem Zahlungsanbieter. Über MCP kommt nie irgendein Inhalt zurück.

Sieh dir das zweite Tool an. Wenn dein Server erfährt, dass der externe Ablauf abgeschlossen ist (ein Webhook, ein Poll; hier als zweites Tool modelliert), sendet `ctx.session.send_elicit_complete(...)` die Benachrichtigung `notifications/elicitation/complete` mit derselben `elicitation_id`. So weiß der Client, dass er *„waiting for payment...“* nicht mehr anzeigen muss. Ohne sie kann der Client nur raten.

## Die Client-Seite {#the-client-side}

Server fragen. Clients antworten, indem sie `Client(...)` einen **`elicitation_callback`** übergeben:

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* Ein Callback behandelt beide Modi. `params` ist eine Union aus `ElicitRequestFormParams` und `ElicitRequestURLParams`; `isinstance` ist die Verzweigung.
* Bei einer URL zeigst du der Person `params.url` und gibst die Action zurück, die sie gewählt hat. Niemals irgendein `content`.
* Bei einem Formular rendert eine echte Anwendung `params.requested_schema` und gibt die Eingabe der Person als `content` zurück. Dieser hier sagt immer Ja mit einer vorgefertigten Antwort – genau der Callback, den du in einem Test willst.
* Den Callback zu übergeben ist zugleich die **Capability-Deklaration**: So erfährt der Server, dass dieser Client gefragt werden kann. Was ein Client sonst noch für einen Server beantworten kann, steht in **[Client-Callbacks](../client/callbacks.md)**.

!!! info
    Elicitation ist ein Request vom *Server* an den *Client*, und solche gibt es nur auf einer
    Session mit klassischem Handshake, deshalb übergibt dieser Client `mode="legacy"`.
    Auf einer **2026-07-28**-Verbindung fragt ein Tool stattdessen, indem es die Frage aus dem Aufruf
    *zurückgibt*; dieser Ablauf steht in **[Multi-Roundtrip-Requests](multi-round-trip.md)**.

### Ausprobieren {#try-it}

Starte die `server.py` des `ctx.elicit`-Formular-Modus (die mit `book_table`) über Streamable HTTP (den Einzeiler dafür hat **[Den Server betreiben](../run/index.md)**), führe dann `main()` des Clients aus und frage `book_table` nach dem ersten Weihnachtstag.

Der Callback gibt die Frage aus, die er bekommen hat:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

Er antwortet mit `{"accept_alternative": True, "date": "2025-12-27"}`, und das Tool, das die ganze Zeit in `await ctx.elicit(...)` gewartet hat, schließt die Buchung ab:

```text
Booked a table for 2 on 2025-12-27.
```

Tausche nun die `server.py` des URL-Modus ein und richte dasselbe `main()` auf `pay_deposit`: Derselbe Callback nimmt den anderen Zweig, gibt den Bezahllink aus, und das Tool kommt mit *„Complete the payment in your browser.“* zurück. Ein Roundtrip, mitten im Aufruf, in beide Richtungen.

!!! check
    Entferne nun `elicitation_callback=` aus dem `Client` und rufe `book_table` noch einmal für den ersten
    Weihnachtstag auf. Der ganze Aufruf schlägt mit einem Protokollfehler fehl:

    ```text
    Elicitation not supported
    ```

    Ein Client, der keinen Callback registriert hat, hat die Capability `elicitation` nie deklariert, also gibt es
    niemanden zum Fragen. Dein Tool hat kein `"decline"` bekommen; es hat eine Exception bekommen. Plane dafür: Jede
    Elicitation braucht eine sinnvolle Antwort auf „Was, wenn ich nicht fragen kann?“.

## Zusammenfassung {#recap}

* Ein Parameter mit der Annotation `Annotated[T, Resolve(fn)]` wird von einem Resolver befüllt, der `Elicit(...)` zurückgibt, wenn er fragen muss. Das funktioniert auf jeder Verbindung.
* Das Schema ist ein flaches Pydantic-Modell: nur primitive Felder, auf dem Rückweg validiert.
* `result.action` ist `"accept"`, `"decline"` oder `"cancel"`; `result.data` existiert nur bei Accept.
* `await ctx.elicit(message, schema=Model)` fragt aus dem Tool-Body heraus, und `await ctx.elicit_url(message, url, elicitation_id)` ist für alles, was nicht durch das Modell laufen darf (`ctx.session.send_elicit_complete(elicitation_id)` meldet, dass der externe Teil erledigt ist). Beide sind Server-zu-Client-Requests: Sie brauchen den Client auf einer Legacy-Verbindung.
* Der Client antwortet mit einem einzigen `elicitation_callback`, der nach dem Typ der Params verzweigt; ihn zu registrieren deklariert die Capability.
* Auf einer 2026-07-28-Verbindung gibt der Server die Frage zurück, statt sie zu pushen; derselbe Callback wird von **[Multi-Roundtrip-Requests](multi-round-trip.md)** gespeist.

Alles unterhalb dieser Rückgabe (die Retry-Schleife, der Schutz von `requestState`, es selbst zu steuern) steht in **[Multi-Roundtrip-Requests](multi-round-trip.md)**.
