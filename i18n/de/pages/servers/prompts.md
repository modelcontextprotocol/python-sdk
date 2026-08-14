---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
  tool: 1
---
# Prompts {#prompts}

Ein **Prompt** ist eine Nachrichtenvorlage, die die Person am Host auswählt.

Tools sind für das Modell gedacht. Ein Prompt ist das Gegenteil: Die Person wählt einen aus einem Menü in ihrem Client (ein Slash-Command, ein Button), füllt die Argumente aus, und die gerenderten Nachrichten landen in der Unterhaltung, als hätte sie sie selbst getippt.

Du deklarierst einen, indem du `@mcp.prompt()` auf eine Funktion setzt, die den Text zurückgibt.

## Dein erster Prompt {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

Das SDK liest dieselben drei Dinge wie bei einem Tool:

* Der **Name** ist der Funktionsname: `review_code`.
* Die **Beschreibung**, die der Client anzeigt, ist der Docstring: `Review a piece of code.`
* Die **Argumente** stammen aus den Parametern. `code` hat keinen Standardwert, also ist es erforderlich.

Das bekommt ein Client von `prompts/list` zurück:

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

Hier gibt es kein JSON Schema. Prompt-Argumente sind eine flache Liste **benannter String-Werte**: ein Formular, das eine Person ausfüllt, keine Payload, die ein Modell zusammenbaut.

### Rendern {#rendering-it}

Der Client rendert die Vorlage mit `prompts/get` und übergibt dabei die Argumente. Deine Funktion läuft, und der `str`, den du zurückgibst, wird zu **einer einzigen User-Nachricht**:

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

Das ist der ganze Lebenslauf eines Prompts: unter seinem Namen aufgelistet, bei Bedarf gerendert, in den Chat eingefügt.

!!! check
    `required` wird durchgesetzt, bevor deine Funktion läuft. Renderst du `review_code` ohne `code`,
    schlägt der Request selbst mit einem JSON-RPC-Fehler (Code `-32603`) fehl:

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    Es gibt kein Fehlerergebnis im Stil eines Tools, das man einem Modell zurückgeben könnte, denn es ist
    kein Modell beteiligt: Der Aufruf löst eine Exception aus. Der Grund (`Missing required arguments: {'code'}`)
    landet im Log deines Servers.

### Ausprobieren {#try-it}

Starte den Server mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Öffne den Tab **Prompts** und wähle `review_code`. Der Inspector zeichnet ein Formular mit einem erforderlichen Feld `code`. Fülle es aus, rendere es, und du bekommst genau die User-Nachricht von oben zurück.

## Mehr als eine Nachricht {#more-than-one-message}

Ein Code-Review ist eine Nachricht. Eine Debugging-Sitzung ist eine Unterhaltung, und ein Prompt kann sie komplett anstoßen.

Gib eine Liste von Nachrichten statt eines `str` zurück:

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` und `AssistantMessage` kommen aus `mcp.server.mcpserver.prompts.base`. Übergib ihnen einen `str`, und sie verpacken ihn für dich in `TextContent`. Die Rolle ist der Klassenname.
* `Message` ist ihre gemeinsame Basisklasse. Verwende sie als Rückgabeannotation.

Das Rendern von `debug_error` erzeugt jetzt drei Nachrichten, in dieser Reihenfolge:

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

Beachte die letzte. Einen `assistant`-Beitrag vorzubelegen ist der Weg, die *nächste* Antwort des Modells zu lenken, ohne dass die Person die Lenkung selbst tippen muss.

## Titel und Argumentbeschreibungen {#titles-and-argument-descriptions}

`review_code` ist ein Funktionsname, keine Beschriftung. Gib dem Client etwas Besseres für den Button und beschreibe jedes Argument, damit sich das Formular von selbst erklärt:

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` ist der menschenlesbare Name, genau wie das `title` eines Tools.
* `Annotated[str, Field(description=...)]` ist dasselbe Muster, mit dem **[Tools](tools.md)** die Parameter eines Tools beschreibt. Hier landet die Beschreibung am Argument statt in einem Schema.
* `language` hat einen Standardwert und ist damit nicht mehr erforderlich.

Der `prompts/list`-Eintrag enthält jetzt alles, was ein Client braucht, um ein gutes Formular zu zeichnen:

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    Wenn du **[Tools](tools.md)** gelesen hast, kennst du schon alles auf dieser Seite. Derselbe Dekorator, derselbe
    Docstring als Beschreibung, dasselbe `Annotated`/`Field`. Das Einzige, was sich ändert: wer
    ihn auslöst (die Person) und wohin das Ergebnis geht (in die Unterhaltung).

## Zusammenfassung {#recap}

* `@mcp.prompt()` auf einer Funktion macht sie zu einem Prompt. Der Name kommt von der Funktion, die Beschreibung vom Docstring.
* Prompts sind **von der Person gesteuert**: Der Client listet sie auf, die Person wählt einen und füllt die Argumente aus.
* Argumente sind eine flache Liste benannter Strings (kein Schema). Ein Parameter mit Standardwert ist optional.
* Gibst du einen `str` zurück, wird daraus eine User-Nachricht. Gib eine Liste von `UserMessage` / `AssistantMessage` zurück, um eine mehrteilige Unterhaltung anzustoßen.
* `title=` und `Field(description=...)` sind das, was ein Client in seiner Oberfläche anzeigt.
* Ein fehlendes erforderliches Argument lässt den ganzen Request fehlschlagen. Es gibt kein Fehlerergebnis pro Prompt.

Serverseitige Autovervollständigung für die Argumente eines Prompts (oder eines Ressourcen-Templates) ist **[Vervollständigungen](completions.md)**.
