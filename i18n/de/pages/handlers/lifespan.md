---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Lifespan {#lifespan}

Die meisten echten Server halten etwas für ihre gesamte Lebensdauer: einen Datenbank-Pool, einen HTTP-Client, ein geladenes Modell.

Du willst das nicht bei jedem Aufruf neu aufbauen, und du willst es sauber schließen. Genau dafür gibt es den **Lifespan** (Start- und Stopp-Phase des Servers).

## Ein typisierter Lifespan {#a-typed-lifespan}

Ein Lifespan ist ein `@asynccontextmanager`, der den Server erhält und per `yield` **ein Objekt** liefert. Was immer du dabei lieferst, steht jedem Handler zur Verfügung, solange der Server läuft.

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

Lies es von unten nach oben:

* `app_lifespan` verbindet die `Database` **vor** dem `yield` und trennt sie **danach**, in einem `finally`. Das sind Start und Stopp.
* Es liefert einen `AppContext`, eine schlichte Dataclass, die die eingerichteten Dinge hält. Heute ein Feld, morgen zehn.
* `MCPServer("Bookshop", lifespan=app_lifespan)` ist die ganze Verdrahtung.
* Im Tool ist das gelieferte Objekt `ctx.request_context.lifespan_context`.

Der Lifespan läuft **einmal**. Er wird betreten, wenn der Server startet (vor dem ersten Request), und verlassen, wenn der Server stoppt. Alle Requests dazwischen teilen sich denselben `AppContext`.

!!! info
    Wenn du schon einmal einen FastAPI-`lifespan` geschrieben hast, kennst du das bereits. Derselbe Dekorator, dasselbe `yield`, dasselbe `finally`.

### Was das Modell sieht {#what-the-model-sees}

Nichts Neues. `ctx` ist ein **Context**-Parameter, also injiziert das SDK ihn, und er landet nie im Eingabeschema:

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` ist das einzige Argument, das das Modell übergeben kann. Der Lifespan ist Sache deines Servers.

Auch `@mcp.resource()`- und `@mcp.prompt()`-Funktionen können einen `ctx`-Parameter annehmen, geschrieben als bloßer `Context` – aus einem Grund, zu dem der nächste Abschnitt kommt. Alles, was `ctx` mitbringt, steht in **[Der Context](context.md)**.

### Es ist wirklich typisiert {#it-really-is-typed}

Sieh dir die Annotation noch einmal an: `ctx: Context[AppContext]`.

Dieser eine Typparameter ist der Grund, warum `ctx.request_context.lifespan_context` für deinen Type Checker ein `AppContext` **ist**. `.db` wird automatisch vervollständigt; `.dbb` ist ein Fehler, bevor du den Server überhaupt startest.

Schreibst du stattdessen einen bloßen `Context`, ist `lifespan_context` als `dict[str, Any]` typisiert: Der Type Checker kann nicht wissen, was dein Lifespan geliefert hat. Das Objekt ist zur Laufzeit immer noch da; du hast nur die Hilfe verloren.

!!! warning
    `Context[AppContext]` ist eine Schreibweise **nur für Tools**. Setzt du sie auf eine `@mcp.resource()`- oder
    `@mcp.prompt()`-Funktion, schlägt jeder Aufruf dieses Handlers fehl. Der Client bekommt einen Fehler zurück,
    und das Server-Log zeigt, warum:

    ```text
    Context is not available outside of a request
    ```

    In Ressourcen und Prompts schreibst du das bloße `ctx: Context`. Das Objekt, das dein Lifespan geliefert hat, ist
    zur Laufzeit immer noch `ctx.request_context.lifespan_context`; du gibst den Typparameter auf, nicht
    das Objekt.

!!! tip
    Es gibt immer einen Lifespan. Übergibst du keinen, liefert der Standard des SDK ein leeres `dict`,
    also ist `ctx.request_context.lifespan_context` `{}`, nie `None`. Dieser Standard ist auch der Grund, warum ein
    bloßer `Context` es als `dict[str, Any]` typisiert.

## Zusehen, wie es passiert {#watch-it-happen}

„Der Start läuft vor dem ersten Request“ ist die Art von Satz, die du nicht einfach glauben müssen solltest.

Reduziere den Server auf den Lebenszyklus: Gib `Database` ein `connected`-Flag, schalte es in `connect()` und `disconnect()` um und füge ein Tool hinzu, das es meldet.

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` lebt aus einem Grund auf Modulebene: damit du es von *außerhalb* des Servers betrachten kannst.

!!! check
    Drei Momente, drei Werte:

    * Bevor der Server startet, ist `database.connected` `False`. Der Import des Moduls hat nichts verbunden.
    * Während er läuft, rufe `database_status` auf, und das Ergebnis ist `"connected"`.
    * Stoppe den Server, und der `finally`-Block läuft: `database.connected` ist wieder `False`.

    Die Arbeit geschah genau dort, wo du sie hingelegt hast: rund um das `yield`, nicht beim Import und nicht pro Request.

## Zusammenfassung {#recap}

* `lifespan=` nimmt einen `@asynccontextmanager`, der den Server erhält und per `yield` ein Objekt liefert.
* Code vor dem `yield` ist der Start. Das `finally` danach ist der Stopp.
* Er läuft einmal, rund um die gesamte Lebensdauer des Servers, nicht pro Request.
* Was immer du per `yield` lieferst, ist `ctx.request_context.lifespan_context` in jedem Tool, jeder Ressource und jedem Prompt.
* `ctx: Context[AppContext]` macht diesen Zugriff in Tools vollständig typisiert. Ressourcen und Prompts nehmen den bloßen `Context`.
* Kein `lifespan=` bedeutet ein leeres `dict`, nie `None`.

Ein Handler, der mitten im Aufruf anhält, um die Person am Host nach etwas zu fragen, das nur sie weiß, ist **[Elicitation](elicitation.md)** (Rückfrage bei der Person am Host).
