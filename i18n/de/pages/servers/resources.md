---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# Ressourcen {#resources}

Eine **Ressource** sind Daten, die du bereitstellst, damit die Anwendung sie lesen kann.

Das ist die Trennlinie. Ein Tool ist etwas, das das **Modell** aufzurufen beschließt. Eine Ressource ist etwas, das die **Anwendung** zu laden beschließt (eine Konfigurationsdatei, einen Datensatz, ein Dokument) und dem Modell als Kontext vorlegt.

Du deklarierst eine, indem du `@mcp.resource(uri)` auf eine ganz normale Python-Funktion setzt.

## Deine erste Ressource {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

Sie hat dieselbe Form wie ein Tool, plus eine Sache: den **URI**. Ressourcen werden adressiert, nicht benannt. Ein Client fragt nach `config://app`, nie nach `get_config`.

Den Rest liest das SDK weiterhin aus der Funktion:

* Der **Name** ist der Funktionsname: `get_config`.
* Die **Beschreibung**, die der Client sieht, ist der Docstring.
* Der **Inhalt** ist das, was du zurückgibst.

Bei `resources/list` bekommt der Client das hier:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

Und wenn er `config://app` liest, läuft deine Funktion, und der Rückgabewert kommt als Text zurück:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    Auflisten ist billig. Deine Funktion wird bei `resources/list` **nicht** aufgerufen, nur bei
    `resources/read`, und nur für den URI, nach dem gefragt wurde. Stelle tausend Ressourcen
    bereit, und du zahlst nur für die, die jemand öffnet.

### Ausprobieren {#try-it}

Starte den Server mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Öffne die URL, die er ausgibt, und wechsle zum Tab **Resources**. `config://app` steht mit seiner Beschreibung in der Liste. Klicke darauf, und der Inspector liest es: Da sind deine zwei Zeilen Konfiguration.

## Ressourcen-Templates {#resource-templates}

Ein URI pro Datensatz skaliert nicht. Setze einen **Platzhalter** in den URI und einen passenden Parameter auf die Funktion:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

`{user_id}` im URI, `user_id: str` an der Funktion. Das ist der ganze Vertrag.

Das ist jetzt ein **Ressourcen-Template**, und es zieht um: Es verlässt `resources/list` und taucht stattdessen in `resources/templates/list` auf – als Muster statt als Adresse:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

Der Client füllt den Platzhalter aus und liest einen konkreten URI: `users://42/profile`, `users://ada/profile`. Eine einzige Funktion beantwortet sie alle, wobei der erkannte Wert als `user_id` übergeben wird:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

Beachte den `uri` im Ergebnis. Es ist der **konkrete** URI, nach dem der Client gefragt hat, nicht das Template.

!!! check
    Platzhalter und Parameter müssen übereinstimmen. Benenne den Funktionsparameter in
    `user` um, während im URI noch `{user_id}` steht, und der Dekorator verweigert sich **beim Import**,
    bevor irgendein Client in die Nähe kommt:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    Eine Abweichung kann immer nur ein Bug sein, also macht das SDK es unmöglich, den Server damit zu starten.

Die Platzhalter-Syntax ist [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570): `{+path}` für Werte über mehrere Segmente, `{?q,lang}` für optionale Query-Parameter und mehr. Außerdem wendet das SDK standardmäßig Pfadsicherheitsprüfungen auf die extrahierten Werte an. Die vollständige Referenz steht in **[URI-Templates und Pfadsicherheit](uri-templates.md)**.

`get_user_profile` kann auch einen Parameter mit der Annotation `Context` entgegennehmen. Das SDK injiziert ihn, ohne ihn je als URI-Parameter zu behandeln, und die Seite **[Der Context](../handlers/context.md)** beschreibt, was er dir bietet.

## Was du zurückgibst {#what-you-return}

Du bist nicht auf `str` beschränkt. Gib jeder Ressource einen `mime_type` und gib zurück, was passt:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` gibt einen `str` zurück, also wird er unverändert gesendet. Das ist der Normalfall.
* `catalog_stats` gibt ein `dict` zurück, also serialisiert das SDK es für dich zu **JSON-Text**:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` gibt `bytes` zurück, also bekommt der Client ein `BlobResourceContents` statt eines `TextResourceContents`, mit deinen Bytes base64-kodiert im Feld `blob`.

Dieselbe Regel gilt für alles andere, was JSON-serialisierbar ist: eine Liste, ein Pydantic-Modell, eine Dataclass. Ist es kein `str` und kein `bytes`, wird es zu JSON.

`mime_type` deklarierst du selbst, und der Standardwert ist `text/plain`. Das SDK untersucht nie, was du zurückgibst, um ihn zu erraten – eine `dict`-Ressource, die du nicht kennzeichnest, wird also weiterhin als Plain Text angekündigt.

!!! tip
    `@mcp.resource()` akzeptiert auch `name=`, `title=` und `description=`, wenn du sie nicht
    aus der Funktion ableiten willst. Und wenn es gar keine Funktion zu schreiben gibt,
    hält `mcp.server.mcpserver.resources` fertige `Resource`-Klassen bereit (`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`), die du
    mit `mcp.add_resource(...)` registrierst.

Ein Client kann eine Ressource außerdem **abonnieren** und benachrichtigt werden, wenn sie sich ändert; das ist die Client-Hälfte der Geschichte, und sie steht in **[Der Client](../client/index.md)**.

## Zusammenfassung {#recap}

* `@mcp.resource(uri)` auf einer Funktion macht sie zur Ressource. Der URI ist die Adresse, der Rückgabewert ist der Inhalt, der Docstring ist die Beschreibung.
* Ein `{placeholder}` im URI macht sie zum **Template**: Es wird unter `resources/templates/list` aufgeführt, und eine einzige Funktion bedient jeden URI, der passt.
* Die Platzhalternamen müssen den Parameternamen der Funktion entsprechen. Machst du es falsch, erfährst du es beim Import, nicht in Produktion.
* Deine Funktion läuft, wenn die Ressource **gelesen** wird, nicht wenn sie aufgelistet wird.
* `str` wird zu Text, `bytes` zu einem base64-Blob, alles andere zu JSON-Text. Mit `mime_type=` kennzeichnest du es.
* Tools sind dafür da, dass das Modell handelt. Ressourcen sind dafür da, dass die Anwendung liest.

Das dritte Primitiv – das, das eine Person aus einem Menü auswählt – sind **[Prompts](prompts.md)**.
