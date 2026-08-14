---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# Erste Schritte {#first-steps}

Die **[Startseite](../index.md)** legt ein hohes Tempo vor: einen Server schreiben, ihn starten, ein Tool aufrufen.

Diese Seite geht es langsam an – mit allen drei Dingen, die ein Server bereitstellen kann, und einem Namen für alles, was unterwegs auftaucht.

## Host, Client und Server {#host-client-and-server}

Drei Wörter, die dir ab hier auf jeder Seite begegnen:

* Ein **Host** ist die LLM-Anwendung: Claude, eine IDE, eine Agent-Laufzeitumgebung. Mit ihm spricht die Person.
* Ein **Client** lebt im Host und spricht MCP. Der Host betreibt einen Client pro Server, mit dem er verbunden ist.
* Ein **Server** ist das, was du mit diesem SDK baust. Er stellt Clients Dinge bereit. Mit dem Modell spricht er nie direkt.

Du schreibst den Server. Hosts sind das Produkt anderer. Das SDK gibt dir außerdem einen `Client`. Mit ihm testest du deine Server, und er taucht weiter unten auf dieser Seite auf.

## Die drei Primitive {#the-three-primitives}

Ein Server stellt genau drei Arten von Dingen bereit. Was sie unterscheidet, ist, **wer über ihren Einsatz entscheidet**:

| Primitiv       | Gesteuert von      | Was es ist                                                         | Beispiel                                |
|----------------|--------------------|--------------------------------------------------------------------|-----------------------------------------|
| **Tools**      | Dem Modell         | Eine Funktion, die das Modell aufruft, um etwas zu tun             | Ein API-Aufruf, ein Datenbank-Schreibzugriff |
| **Ressourcen** | Der Anwendung      | Daten, die der Host in den Kontext des Modells lädt                | Der Inhalt einer Datei, eine API-Response |
| **Prompts**    | Der Person am Host | Eine wiederverwendbare Nachrichtenvorlage, die die Person über ihren Namen aufruft | Ein Slash-Befehl, ein Menüeintrag |

„Gesteuert von“ ist der ganze Sinn dieser Aufteilung. Ein Tool läuft, weil das **Modell** entschieden hat, es aufzurufen. Eine Ressource wird angehängt, weil die **Anwendung** entschieden hat, dass das Modell sie braucht. Ein Prompt läuft, weil die **Person** ihn ausgewählt hat.

!!! info
    Wenn du schon einmal eine Web-API gebaut hast, hast du das meiste Gespür bereits: Eine
    **Ressource** ist ein `GET` (sie lädt Daten und ändert nichts) und ein **Tool** ist ein `POST`
    (es erledigt Arbeit und kann Seiteneffekte haben). Ein **Prompt** hat keine HTTP-Entsprechung;
    er ähnelt eher einer gespeicherten Abfrage, die die Person über ihren Namen ausführt.

## Ein Server, alle drei {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

Drei gewöhnliche Funktionen, drei Dekoratoren. Jeder Dekorator ist die gesamte Registrierung:

* `@mcp.tool()` macht `add` zu einem **Tool**.
* `@mcp.resource("greeting://{name}")` macht `greeting` zu einem **Ressourcen-Template**: Das `{name}` im URI ist der Parameter der Funktion.
* `@mcp.prompt()` macht `summarize` zu einem **Prompt**. Der String, den die Funktion zurückgibt, wird zu einer User-Nachricht.

Alles andere (den Namen, die Beschreibung, das Argument-Schema) liest das SDK aus der Funktion selbst: ihrem Namen, ihrem Docstring, ihren Type Hints. Du hast nichts davon separat deklariert.

!!! tip
    Die beiden Hälften des SDK haben zwei Importpfade: `from mcp import Client` und
    `from mcp.server import MCPServer`. Ein `from mcp import MCPServer` gibt es nicht.

### Ausprobieren {#try-it}

Starte ihn mit dem MCP Inspector:

```console
uv run mcp dev server.py
```

Öffne die URL, die er ausgibt. Der Inspector hat einen Tab pro Primitiv; geh sie der Reihe nach durch.

**Tools.** Ein Eintrag: `add`, beschrieben als *Add two numbers.* Das Formular hat ein erforderliches Ganzzahlfeld für `a` und ein weiteres für `b`. Füll sie aus, ruf das Tool auf, und das Ergebnis ist `3`. Der Inspector hat dieses Formular aus `a: int, b: int` gebaut. Jeder andere Client macht es genauso.

**Resources.** Die Liste *Resources* ist leer. `greeting` steht unter **Resource Templates**, weil `greeting://{name}` einen Parameter hat: Es gibt keine einzelne Ressource aufzulisten, bis jemand einen `name` liefert. Gib ihm `World` und lies sie:

```text
Hello, World!
```

**Prompts.** Ein Eintrag: `summarize`, mit einem einzigen erforderlichen Argument `text`. Ruf ihn mit etwas Text ab, und du erhältst eine Nachricht mit `role: user` und deinem gerenderten String als Inhalt. Mehr ist ein Prompt nicht: eine Funktion, die Nachrichten baut.

Der Inspector hat deinen Server über **stdio** betrieben, einen der Transporte, die ein MCP-Server sprechen kann. Du wählst noch keinen aus; dafür gibt es die Seite **[Den Server betreiben](../run/index.md)**.

## Capabilities {#capabilities}

Du hast im Inspector drei Tabs gesehen. Woher wusste er, dass es drei sind?

Wenn sich ein Client verbindet, deklariert der Server seine **Capabilities**: welche Familien von Requests er beantwortet. Der Client entscheidet anhand dieser Deklaration, wonach er überhaupt fragt. Du hast sie nie geschrieben; `MCPServer` deklariert sie für dich.

Sieh es dir selbst an. Der `Client` des SDK nimmt das Server-Objekt direkt entgegen und verbindet sich **im Speicher** damit (kein Subprozess, kein Port):

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

Dieses Dictionary sind die deklarierten **Capabilities** deines Servers. Es ist das Erste, was jeder Client beim Verbinden erfährt:

| Capability  | Der Client darf jetzt aufrufen                              |
|-------------|-------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                  |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                               |

`MCPServer` bedient alle drei Primitive, also werden immer alle drei deklariert.

Achte darauf, was fehlt. `completions` (die automatische Vervollständigung von Argumenten für Ressourcen-Templates und Prompts) braucht einen Handler, den du schreibst. Dieser Server hat keinen, also fehlt die Capability, und ein wohlerzogener Client fragt gar nicht erst. Das ist die Regel für alles Optionale: Registriere das Ding, und die Capability erscheint; **[Vervollständigungen](../servers/completions.md)** zeigt es.

!!! info
    `Client(mcp)` ist derselbe In-Memory-Client, mit dem jedes Beispiel in dieser Dokumentation
    getestet wird, und so testest du auch deine. Er bekommt eine ganze Seite: **[Testen](testing.md)**.

## Was du nicht geschrieben hast {#what-you-did-not-write}

Blick auf diese Seite zurück. Du hast drei kleine Python-Funktionen geschrieben. **Nicht** geschrieben hast du:

* Ein JSON-Schema. `a: int, b: int` *ist* das Schema für `add`.
* Einen Request-Handler. `tools/list`, `resources/read`, `prompts/get`: alles für dich bedient.
* Eine Capability-Deklaration. `MCPServer` hat sie für dich erstellt.
* Eine Zeile Protokoll. Die Versionsaushandlung, das JSON-RPC-Framing, der Austausch der Capabilities: Das alles passierte in `mcp dev` und `Client(mcp)`, und du hast es nie gesehen.

Dieses Verhältnis ist der ganze Sinn des SDK.

## Zusammenfassung {#recap}

* Ein **Host** ist die LLM-App, ein **Client** ist ihre MCP-sprechende Hälfte, ein **Server** ist das, was du baust.
* Tools steuert das **Modell**, Ressourcen steuert die **Anwendung**, Prompts steuert die **Person**.
* Ein Dekorator pro Primitiv: `@mcp.tool()`, `@mcp.resource(uri)`, `@mcp.prompt()`. Name, Beschreibung und Schema kommen aus der Funktion.
* Ein URI mit einem `{param}` ergibt ein Ressourcen-**Template**, das getrennt von konkreten Ressourcen aufgelistet wird.
* Die **Capabilities** des Servers werden für dich deklariert, und ein Client fragt nur nach dem, was ein Server deklariert.
* `Client(mcp)` verbindet sich im Speicher mit dem Server-Objekt: deine Testumgebung vom ersten Tag an.

Als Nächstes kommt **[Mit einem echten Host verbinden](real-host.md)**: dieser Server in Claude Desktop oder einer IDE, in echt. Danach **[Testen](testing.md)**: eine Seite, ein In-Memory-Client, und du musst nie raten, ob es funktioniert. Danach bekommt jedes Primitiv seine eigene Seite, angefangen mit dem, das das Modell steuert: **[Tools](../servers/tools.md)**.
