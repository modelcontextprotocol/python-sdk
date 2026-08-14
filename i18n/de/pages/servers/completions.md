---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# Vervollständigungen {#completions}

Ein Client, der eine UI auf deinem Server aufbaut, möchte Argumentwerte automatisch vervollständigen, während die Person tippt: Sprachnamen, Repository-Namen, Dateipfade.

Mit **Vervollständigungen** liefert dein Server diese Vorschläge.

## Etwas zum Vervollständigen {#something-worth-completing}

Vervollständigungen gibt es für genau zwei Dinge: die Argumente eines **Prompts** und die Parameter eines **Ressourcen-Templates**. Beginne also mit einem Server, der von beidem eines hat:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

Noch hat hier nichts mit Vervollständigungen zu tun.

* `review_code` nimmt eine `language` entgegen. Niemand sollte raten müssen, welche Schreibweisen du akzeptierst.
* `github_repo` nimmt einen `owner` und ein `repo` entgegen. Freitextfelder für beide ergeben ein schlechtes Formular.

## Der Vervollständigungs-Handler {#the-completion-handler}

Füge **eine** mit `@mcp.completion()` dekorierte Funktion hinzu:

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* Es gibt einen Handler pro Server. Jeder Vervollständigungs-Request landet hier, und du verzweigst danach, was gerade vervollständigt wird.
* Er muss mit `async def` definiert sein: Das SDK wartet per await auf ihn.
* Er erhält drei Argumente:
  * `ref`: um *welchen* Prompt oder welches Ressourcen-Template es geht, als `PromptReference` oder `ResourceTemplateReference`. Mit `isinstance` unterscheidest du die beiden.
  * `argument`: `argument.name` ist das Argument, das vervollständigt wird, `argument.value` das, was die Person bisher getippt hat.
  * `context`: die bereits aufgelösten Argumente. Ignoriere es vorerst.
* Du gibst eine `Completion(values=[...])` zurück, oder `None`, wenn du nichts anzubieten hast.

!!! tip
    `argument.value` ist das Präfix, das die Person getippt hat. Das SDK filtert **nicht** für dich: Was
    immer du in `values` packst, zeigt die UI an. Das `startswith` schreibst du selbst.

### Ausprobieren {#try-it}

Steuere ihn mit dem In-Memory-`Client` aus **[Testen](../get-started/testing.md)** an. Rufe
`client.complete()` mit `ref=PromptReference(name="review_code")` und
`argument={"name": "language", "value": "py"}` auf:

```python
result.completion.values  # ['python']
```

* `ref` ist derselbe Referenztyp, den dein Handler erhält.
* `argument` ist ein einfaches dict mit genau zwei Schlüsseln, `name` und `value`.

Schickst du ein leeres `value`, bekommst du die ganze Liste zurück. `lang.startswith("")` ist für jede Sprache wahr:

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

Fragst du nach `code` (einem Argument, das dein Handler nicht kennt), gibt er `None` zurück, was das SDK in eine leere Liste verwandelt:

```python
result.completion.values  # []
```

`None` bedeutet *„keine Vorschläge“*, nie einen Fehler. Eine UI fällt auf ein einfaches Textfeld zurück.

## Eine Capability, die du nie deklariert hast {#a-capability-you-never-declared}

Den Handler zu registrieren ist die Deklaration. Verbinde einen Client und sieh nach:

```python
client.server_capabilities.completions  # CompletionsCapability()
```

Du hast `completions` nirgends aufgeführt. Das SDK hat den Handler gesehen und die Capability für dich deklariert. Jede *optionale* Capability funktioniert so: Der Handler ist die Deklaration. (Die drei Primitive sind nicht optional: `MCPServer` deklariert sie immer, mit oder ohne Handler.)

!!! check
    Geh zurück zur ersten `server.py` (der ohne Handler) und frage trotzdem. Der Aufruf schlägt
    mit einem JSON-RPC-Fehler fehl:

    ```text
    Method not found
    ```

    Und `client.server_capabilities.completions` ist `None`. Genau dafür ist die Capability da: Ein
    Client, der sich korrekt verhält, prüft sie und schickt den Request, den du nicht beantworten kannst, gar nicht erst.

## Abhängige Argumente {#dependent-arguments}

`github://repos/{owner}/{repo}` hat zwei Parameter, und die sinnvollen Werte für `repo` hängen davon ab, welcher `owner` zuerst gewählt wurde.

Dafür ist `context` da. Es trägt die Argumente, die die Person **bereits aufgelöst** hat:

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* Der neue Zweig greift beim Parameter `repo` des Templates.
* `context.arguments` ist ein `dict[str, str] | None` mit den bisher gewählten Werten (hier `owner`).
* Noch kein `owner` bedeutet keine sinnvollen Vorschläge, also gibt der Handler `None` zurück.

Der Client schickt diese aufgelösten Werte mit `context_arguments=`. Diesmal ist `ref` eine
`ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`. Frage mit leerem
`value` nach `repo` und übergib `context_arguments={"owner": "modelcontextprotocol"}`:

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

Lässt du `context_arguments=` weg, gibt derselbe Aufruf `[]` zurück. Der Handler kann nicht wissen, welche Repos er anbieten soll, solange er den Owner nicht kennt.

!!! info
    `Completion` nimmt außerdem `total=` und `has_more=` entgegen. Setze sie, wenn `values` ein Ausschnitt einer
    längeren Liste ist, damit eine UI *„und 200 weitere“* anzeigen kann. Die meisten Handler brauchen sie nie.

## Zusammenfassung {#recap}

* Vervollständigungen sind Vorschläge für **Prompt-Argumente** und **Parameter von Ressourcen-Templates**. Sonst nichts.
* `@mcp.completion()` registriert den einen Handler. Er ist `async def (ref, argument, context) -> Completion | None`.
* Verzweige nach `isinstance(ref, ...)` und nach `argument.name`. Filtere selbst nach `argument.value`.
* `None` wird zu einer leeren Liste. Es ist nie ein Fehler.
* `context.arguments` enthält die bereits aufgelösten Werte; der Client liefert sie als `context_arguments=`.
* Die Capability `completions` erscheint, sobald du den Handler registrierst. Ohne ihn endet der Request mit `Method not found`.

Vorschläge helfen, solange die Person einen Prompt oder ein Template noch *ausfüllt*; um ihr *mitten* in einem Tool-Aufruf eine Frage zu stellen, brauchst du **[Elicitation](../handlers/elicitation.md)** (Rückfrage bei der Person am Host). Alles, was ein Tool außer Text zurückgeben kann, steht in **[Bilder, Audio und Icons](media.md)**.
