---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
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
    Wenn du **[Tools](tools.md)** gelesen hast, kennst du bis hierher schon alles. Derselbe Dekorator, derselbe
    Docstring als Beschreibung, dasselbe `Annotated`/`Field`. Das Einzige, was sich ändert: wer
    ihn auslöst (die Person) und wohin das Ergebnis geht (in die Unterhaltung).

## Mehr als Text {#more-than-text}

`UserMessage` und `AssistantMessage` akzeptieren überall dort, wo sie einen `str` akzeptieren, auch einen Content-Block oder einen `Image`-/`Audio`-Helfer. Zwei Fälle kommen bei Prompts vor: ein Dokument anhängen und ein Bild anhängen.

### Eine Datei einbetten {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* Der Styleguide ist eine Ressource unter `style://python` (die behandelt **[Ressourcen](resources.md)**), gelesen aus einer `style-guide.md` neben `server.py`. Lege dort eine beliebige Markdown-Datei ab.
* `EmbeddedResource(resource=TextResourceContents(...))`, beide aus `mcp.types`, trägt die Datei samt URI und MIME-Typ als erste Nachricht; die Anweisung, die sich darauf bezieht, folgt als reiner Text.
* Einbetten, statt den Guide in den f-String einzufügen, erlaubt dem Client, ihn als Anhang zu zeigen und `style://python` später erneut zu öffnen, und das Modell erhält die Datei unverändert. Für eine Binärdatei nimm `BlobResourceContents` mit einem base64-kodierten `blob`.

Gerendert ist der `content` der ersten Nachricht ein `resource`-Block:

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### Ein Bild anhängen {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` ist der Helfer aus **[Bilder, Audio und Icons](media.md)**. `UserMessage` wandelt ihn beim Rendern des Prompts in einen `ImageContent`-Block um (die Datei base64-kodiert, der MIME-Typ aus `.png` erraten); `Audio` wird auf dieselbe Weise zu einem `AudioContent`.
* Lege ein beliebiges PNG namens `architecture.png` neben `server.py`. Prompt-Argumente sind Strings, daher kommt das Bild immer vom Server; `component` liefert nur die Worte.

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## Die Liste zur Laufzeit ändern {#changing-the-list-at-runtime}

Prompts lassen sich hinzufügen, während Clients verbunden sind, z. B. damit eine Person eine Anweisung als eigenen Menüeintrag speichern kann. Registriere den Prompt und benachrichtige dann:

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` registriert eine Funktion genau so, wie `@mcp.prompt()` es täte, und `mcp.remove_prompt(name)` ist die Umkehrung. `add_prompt` behält einen vorhandenen Eintrag gleichen Namens, statt ihn zu überschreiben; deshalb entfernt das Tool zuerst einen etwaigen alten, damit Speichern ein Ersetzen ist. `prompts/list` spiegelt die Änderung sofort wider.
* `await ctx.notify_prompts_changed()` sendet `notifications/prompts/list_changed` an jeden `2026-07-28`-Client, der auf einem `subscriptions/listen`-Stream lauscht (**[Abonnements](../handlers/subscriptions.md)**). `await ctx.session.send_prompt_list_changed()` sendet sie an den aufrufenden Client, wenn dieser älter als 2026 ist (**[Legacy-Clients unterstützen](../run/legacy-clients.md)**). Rufe beide auf; jede tut nichts, wenn es niemanden zu benachrichtigen gibt.
* Ein Client, der die Benachrichtigung erhält, ruft `prompts/list` erneut auf. Im Python-`Client` ist das `async with client.listen(prompts_list_changed=True) as sub:`, was ein `PromptsListChanged`-Event liefert.

## Zusammenfassung {#recap}

* `@mcp.prompt()` auf einer Funktion macht sie zu einem Prompt. Der Name kommt von der Funktion, die Beschreibung vom Docstring.
* Prompts sind **von der Person gesteuert**: Der Client listet sie auf, die Person wählt einen und füllt die Argumente aus.
* Argumente sind eine flache Liste benannter Strings (kein Schema). Ein Parameter mit Standardwert ist optional.
* Gibst du einen `str` zurück, wird daraus eine User-Nachricht. Gib eine Liste von `UserMessage` / `AssistantMessage` zurück, um eine mehrteilige Unterhaltung anzustoßen.
* `title=` und `Field(description=...)` sind das, was ein Client in seiner Oberfläche anzeigt.
* Ein fehlendes erforderliches Argument lässt den ganzen Request fehlschlagen. Es gibt kein Fehlerergebnis pro Prompt.
* Verpacke eine `EmbeddedResource` oder ein `Image` in eine `UserMessage`, um ein Dokument oder ein Bild anzuhängen.
* Füge Prompts zur Laufzeit mit `mcp.add_prompt(...)` / `mcp.remove_prompt(...)` hinzu oder entferne sie, dann `await ctx.notify_prompts_changed()` und `await ctx.session.send_prompt_list_changed()`.

Serverseitige Autovervollständigung für die Argumente eines Prompts (oder eines Ressourcen-Templates) ist **[Vervollständigungen](completions.md)**.
