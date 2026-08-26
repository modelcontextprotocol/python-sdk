---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# Session-Gruppen {#session-groups}

Ein `Client` verbindet sich mit einem Server. Echte Anwendungen brauchen oft mehrere (einen Suchserver, einen Datenbankserver, eine interne API) und jonglieren am Ende für jeden davon mit einer Verbindung und einer Tool-Liste.

**`ClientSessionGroup`** ist ein einziges Objekt, das viele Verbindungen hält und alles, was sie bereitstellen, zu einer einzigen Sicht zusammenführt.

## Zwei Server {#two-servers}

Beginne mit zwei gewöhnlichen Servern. Sie haben nichts miteinander zu tun, also haben beide ihr Tool ganz selbstverständlich `search` genannt:

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## Eine Gruppe {#one-group}

Erzeuge eine `ClientSessionGroup` und rufe **`connect_to_server`** einmal pro Server auf:

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` nimmt Transport-Parameter entgegen, kein Server-Objekt: `StdioServerParameters` (aus `mcp`), um einen Subprozess zu starten, oder `StreamableHttpParameters` / `SseServerParameters` (aus `mcp.client.session_group`) für einen Server, der bereits unter einer URL lauscht.
* `group.tools` ist ein `dict[str, Tool]` mit den Tools aller verbundenen Server. `group.resources` und `group.prompts` haben dieselbe Form.
* `group.call_tool(name, arguments)` schlägt den Namen nach, findet die Session, der er gehört, und leitet den Aufruf weiter. Du gibst nie an, welcher Server gemeint ist.

!!! check
    Lege `client.py` neben die beiden Server und führe es aus. Das zweite `connect_to_server` verweigert sich:

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    Das ist ein `MCPError`, ausgelöst, bevor irgendetwas vom zweiten Server registriert ist. Ein Name muss
    in der **gesamten** Gruppe eindeutig sein, und zwei Server, die du nicht kontrollierst, kollidieren früher oder später.

## `component_name_hook` {#component_name_hook}

Du behebst das in der Gruppe, nicht in den Servern. Übergib eine Funktion von `(name, server_info)`, und die Gruppe wendet sie auf jeden Namen an, den sie registriert:

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

Führe es erneut aus. `print(sorted(group.tools))` zeigt jetzt beide:

```text
['Library.search', 'Web.search']
```

* Der **Schlüssel** gehört dir. `by_server` hat ihn aus `server_info.name` gebaut, dem Namen, mit dem jeder `MCPServer(...)` erzeugt wurde.
* Das `Tool` darin bleibt unverändert: `group.tools["Web.search"].name` ist weiterhin `"search"`, und das ist der Name, den `call_tool` auf die Leitung legt. Das Präfix verlässt deinen Prozess nie.
* Es betrifft nicht nur Tools. Die Ressource `hours` der Bibliothek wird als `Library.hours` registriert.

!!! tip
    Der Hook läuft auf **jedem** Namen von **jedem** Server, nicht nur bei Konflikten: Es gibt keinen
    Modus „Präfix nur bei Kollision“. Wähle ein Schema und lass es überall gelten.

## Server hinzufügen und entfernen {#adding-and-removing-servers}

`connect_to_server` gibt die `ClientSession` zurück, die es geöffnet hat. Behalte sie, falls du diesen Server jemals wieder loswerden willst: `await group.disconnect_from_server(session)` entfernt seine Tools, Ressourcen und Prompts aus der Gruppe.

Hältst du bereits eine verbundene `ClientSession` (`Client.session` ist eine), übergib sie an `await group.connect_with_session(server_info, session)`, statt einen neuen Transport zu öffnen. Sie wird genauso zusammengeführt. Die Gruppe schließt nie eine Session, die sie nicht selbst geöffnet hat. `server_info` benennt den Server für die Komponenten-Präfixe; auf einer Verbindung der 2026er-Generation kann `client.server_info` `None` sein (die Identität ist optional), übergib in diesem Fall also deine eigene `Implementation(name=..., version=...)`.

## Der klassische Handshake {#the-classic-handshake}

`ClientSessionGroup` baut auf `ClientSession` auf, nicht auf `Client`. Jedes `connect_to_server` führt den klassischen `initialize`-Handshake aus. Es sendet nie die `server/discover`-Probe, die in **[Protokollversionen](../protocol-versions.md)** beschrieben ist. Jeder MCP-Server versteht diesen Handshake, das kostet dich also keinerlei Kompatibilität; es bedeutet nur, dass eine Gruppe den älteren, langsameren Weg zu einem Server nimmt, der es besser könnte.

## Zusammenfassung {#recap}

* `ClientSessionGroup` hält viele Server-Verbindungen und führt deren Tools, Ressourcen und Prompts in je ein `dict` zusammen.
* `connect_to_server(params)` pro Server. Es nimmt Transport-Parameter entgegen, nie das Server-Objekt oder die URL, die ein `Client` entgegennimmt.
* `group.call_tool(name, arguments)` leitet den Aufruf für dich an den zuständigen Server weiter.
* Namen müssen in der gesamten Gruppe eindeutig sein; zwei Server mit einem `search`-Tool können nicht ohne Weiteres nebeneinander bestehen.
* `component_name_hook=` schreibt jeden registrierten Namen um. Der Dict-Schlüssel ändert sich, der Name auf der Leitung nicht.
* `connect_with_session` fügt eine Session hinzu, die du bereits hältst; `disconnect_from_server` entfernt eine.

Der Handshake, den eine Gruppe spricht (und der schnellere, den ein `Client` bevorzugt), ist Thema von **[Protokollversionen](../protocol-versions.md)**.
