---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# Mit einem echten Host verbinden {#connect-to-a-real-host}

Ein **Host** ist die Anwendung, in der dein Server am Ende läuft: Claude Desktop, Claude Code, eine IDE. Der Host ist das, womit die Person spricht. In ihm startet ein MCP-**Client** deinen Server als Kindprozess und spricht mit ihm über stdin und stdout dieses Prozesses.

Das heißt: Sich mit einem Host zu verbinden ist eine einzige Handlung. Du nennst ihm **den Befehl, der deinen Server startet**. Alles auf dieser Seite (zwei CLI-Befehle, drei JSON-Dateien) ist nur ein anderer Ort für genau diesen Befehl.

## Ein Server, jeder Host {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

Zwei Tools und eine Ressource, eine Datei. Drei Dinge an dieser Datei sind für jeden der folgenden Hosts wichtig:

* `mcp.run()` ohne Argumente startet einen **stdio**-Server: Er blockiert, liest Protokollnachrichten von stdin und schreibt sie auf stdout. Das ist der Transport, den jeder Host auf dieser Seite spricht. Der Host startet deine Datei als Kindprozess und besitzt diese beiden Pipes – deshalb bedeutet Verbinden immer nur „hier ist der Befehl“. Du wählst nie einen Port, und nichts lauscht auf einem.
* `run()` steht unter `if __name__ == "__main__":`. Alles Folgende **importiert** diese Datei, statt sie auszuführen. Ein ungeschütztes `run()` würde also einen Server starten, sobald irgendetwas das Modul lädt.
* Das Server-Objekt ist eine globale Variable auf Modulebene namens `mcp`. Nach diesem Namen sucht `mcp run` (`server` und `app` funktionieren auch). Nennst du es anders, gibst du den Namen explizit an: `mcp run server.py:bookshop`.

Das war die letzte Zeile Python auf dieser Seite. Ab hier geht es nur noch um Host-Konfiguration.

## Der Startbefehl {#the-launch-command}

Jeder der folgenden Hosts bekommt denselben Befehl:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Ein Befehl für alle, weil `uv run --with` das SDK an Ort und Stelle in eine frische Umgebung auflöst: Er funktioniert aus jedem Verzeichnis und braucht weder ein Projekt noch eine virtuelle Umgebung, die du aktivieren müsstest. Das zählt hier mehr als irgendwo sonst, denn ein Host startet deinen Server aus *seinem* Arbeitsverzeichnis mit einer fast leeren Umgebung, nicht aus deiner Shell.

Es ist außerdem der Befehl, den `mcp install` für dich in die Konfiguration von Claude Desktop schreibt (siehe unten). Was du von Hand tippst und was das Tool erzeugt, stimmt also überein – bis auf die exakte Versionsangabe, die das Tool ergänzt.

!!! tip "Wenn ein Host `uv` nicht findet"
    Ein Host startet deinen Server mit einem minimalen `PATH`, und `uv` liegt womöglich nicht
    darauf. Ersetze das bloße `uv` durch den absoluten Pfad aus `which uv` (macOS/Linux) oder
    `where uv` (Windows). Genau das schreibt auch `mcp install`.

!!! note "Diese Seite beschreibt den lokalen Fall"
    Alles hier betreibt deinen Server auf der Maschine, auf der auch der Host läuft: Der Host
    startet deine Datei, über stdio. Für ein persönliches Tool oder eines für einen einzelnen
    Rechner ist das genau richtig. Um einen Server an Leute zu geben, die deine Datei *nicht*
    haben, verteilst du eine **URL**, keinen Befehl: dasselbe `mcp`-Objekt, ausgeliefert über
    Streamable HTTP. **[Den Server betreiben](../run/index.md)** fasst diese Entscheidung in
    einer Tabelle zusammen, und **[Bereitstellen und skalieren](../run/deploy.md)** ist der Weg
    von dort zu einem echten Hostnamen.

    Und ein Host ist nichts weiter als eine Anwendung mit einem MCP-Client darin. Dein eigenes
    Python kann also die Rolle des Hosts übernehmen: **[Client-Transporte](../client/transports.md)**
    startet genau diese Datei als Subprozess mit `stdio_client(...)`, und **[Testen](testing.md)**
    verbindet sich im Speicher mit ihr, ganz ohne Prozess.

## Claude Desktop {#claude-desktop}

Der eine Host, den das SDK für dich konfigurieren kann:

```bash
uv run mcp install server.py
```

Das ist alles. `mcp install` importiert die Datei, um den Namen des Servers zu lesen, findet die Konfigurationsdatei von Claude Desktop und schreibt den Startbefehl hinein. Nebenbei wandelt es deinen Pfad in einen absoluten um, damit du es nicht tun musst.

Daran ist nichts Geheimnisvolles. Das ist der Eintrag, den es schreibt:

```json
{
  "mcpServers": {
    "Bookshop": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--frozen",
        "--with",
        "mcp[cli]==2.0.0",
        "mcp",
        "run",
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

Das ist der Startbefehl aus dem Abschnitt oben mit drei Ergänzungen: dem absoluten Pfad zu `uv`, `--frozen`, damit `uv` nie ein Lockfile umschreibt, das zufällig in der Nähe liegt, und einer exakten Festlegung auf die `mcp`-Version, die du installiert hast. Er landet in `claude_desktop_config.json`, und die liegt hier:

* **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Du kannst diese Datei von Hand schreiben. `mcp install` gibt es, damit dir dabei nicht der klassische Fehler (ein relativer Pfad) unterläuft.

Beende Claude Desktop vollständig (nicht nur das Fenster) und öffne es erneut.

!!! warning
    `mcp install` schlägt mit `Claude app not found` fehl, wenn das *Konfigurationsverzeichnis*
    von Claude Desktop noch nicht existiert. Installiere Claude Desktop und starte es einmal:
    Dabei wird das Verzeichnis angelegt.

!!! tip
    Claude Desktop startet deinen Server in einem eigenen Prozess, die Umgebungsvariablen deiner
    Shell sind dort also nicht vorhanden. `uv run mcp install server.py -v API_KEY=abc123` (oder
    `-f .env`) trägt sie in das Feld `env` des Eintrags ein. `--name` überschreibt den Namen des
    Eintrags; standardmäßig ist es der `name` des Servers.

## Claude Code {#claude-code}

Es gibt keine Datei zu bearbeiten. Registriere den Server mit dem `claude`-CLI; alles nach `--` ist der Startbefehl.

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Führe `/mcp` in einer Claude-Code-Session aus, um zu prüfen, dass `bookshop` verbunden ist und seine Tools aufgelistet werden.

## Cursor {#cursor}

Lege `.cursor/mcp.json` im Wurzelverzeichnis deines Projekts an.

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Dasselbe `command` plus `args`, unter demselben Schlüssel `mcpServers`, den auch Claude Desktop verwendet. Der Server erscheint in den MCP-Einstellungen von Cursor mit beiden Tools.

## VS Code {#vs-code}

Lege `.vscode/mcp.json` im Wurzelverzeichnis deines Projekts an.

```json
{
  "servers": {
    "bookshop": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

Zwei Unterschiede zur Datei von Cursor, und es sind die einzigen zwei: Der umschließende Schlüssel heißt `servers`, nicht `mcpServers`, und jeder Eintrag deklariert seinen `type`. Bestätige die Vertrauensabfrage, dann zeigt **MCP: List Servers** in der Befehlspalette `bookshop` als laufend an.

!!! note
    Du brauchst VS Code 1.99 oder neuer mit angemeldeter **GitHub Copilot**-Erweiterung (Copilot
    Free genügt), und Copilot Chat muss im Modus **Agent** sein, denn kein anderer Modus ruft
    Tools auf.

## Der Server erscheint nicht {#it-doesnt-show-up}

Bevor du irgendeine Host-Konfiguration anfasst, führe den Startbefehl selbst aus:

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

Es wird nichts ausgegeben, und der Befehl kehrt nicht zurück. Diese Stille ist richtig: Ein stdio-Server wartet darauf, dass ein Host zuerst auf stdin spricht (`Ctrl-C` beendet ihn). Ein Traceback oder ein sofortiges Beenden ist der eigentliche Fehler – und jetzt kannst du ihn lesen, statt ihn durch einen Host hindurch zu erraten.

Sobald der Befehl dasteht und wartet, bleibt fast immer eine von drei Ursachen:

* **Ein relativer Pfad.** Der Host startet deinen Server aus *seinem* Arbeitsverzeichnis, nicht aus dem, in dem du ihn registriert hast. `server.py`, wo `/absolute/path/to/server.py` nötig wäre, ist der mit Abstand häufigste Fehler. Findet der Host auch `uv` nicht, muss dieser Pfad ebenfalls absolut sein.
* **Der Host läuft noch mit seiner alten Konfiguration.** Hosts lesen ihre Konfiguration beim Start. Gerade Claude Desktop musst du *vollständig beenden* (nicht nur das Fenster schließen) und neu öffnen, bevor eine Änderung an `claude_desktop_config.json` wirkt.
* **Etwas hat stdout außerhalb des umgeleiteten Zeitfensters erreicht.** Bei stdio *ist* stdout das Protokoll. Das SDK leitet während des Betriebs geflushte Streuausgaben nach stderr um. Aber Ausgaben, die vorher auf stdout geflusht werden (ein Wrapper-Skript mit echo, ein `print()` zur Importzeit in einem ungepufferten Prozess), oder ein gepuffertes `print()`, das beim Beenden des Interpreters geleert wird, übergeben dem Host eine kaputte Nachricht, und er trennt die Verbindung. Logge mit der Standardkonfiguration von `logging`, deren stderr-Handler jeden Eintrag sofort flusht; eigene Handler müssen stdout ebenfalls meiden. Alles Weitere steht in **[Logging](../handlers/logging.md)**.

Claude Desktop führt pro Server ein Log: `mcp-server-<NAME>.log` ist das stderr deines Servers, neben `mcp.log` für Verbindungen, unter `~/Library/Logs/Claude` auf macOS und `%APPDATA%\Claude\logs` auf Windows.

Für alles jenseits dieser drei ist **[Fehlerbehebung](../troubleshooting.md)** die richtige Seite.

## Zusammenfassung {#recap}

* Ein **Host** (Claude Desktop, eine IDE) betreibt einen MCP-Client, der deinen Server als Kindprozess über stdio startet. Verbinden heißt, ihm einen einzigen Startbefehl zu geben.
* Dieser Befehl lautet `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`: kein venv zu aktivieren, funktioniert aus jedem Verzeichnis.
* **Claude Desktop** ist der eine Host, den `mcp install` für dich konfiguriert. Es schreibt genau diesen Befehl (plus den absoluten Pfad zu `uv`, `--frozen` und eine exakte Festlegung auf die installierte Version) in `claude_desktop_config.json`, damit du es nie selbst tun musst.
* **Claude Code** ist `claude mcp add bookshop -- <launch command>`. **Cursor** ist `.cursor/mcp.json` unter `mcpServers`. **VS Code** ist `.vscode/mcp.json` unter `servers`, jeder Eintrag mit einem `type`.
* Überall absolute Pfade, den Host nach jeder Änderung an seiner Konfiguration neu starten, und nie etwas anderes als das SDK auf stdout schreiben lassen.

Jeder Host auf dieser Seite hat sich mit derselben Datei verbunden, mit demselben Befehl. Was diese Datei *bereitstellen* kann, ist der Rest dieser Dokumentation: **[Tools](../servers/tools.md)**, **[Ressourcen](../servers/resources.md)** und jeder Transport außer stdio in **[Den Server betreiben](../run/index.md)**.
