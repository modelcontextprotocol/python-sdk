---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# Den Server betreiben {#running-your-server}

`mcp.run()` startet den Server.

Die einzige Entscheidung, die du triffst, ist der **Transport**: wie sich die Bytes zwischen deinem Server und seinem Client tatsächlich bewegen.

## Einen Transport wählen {#pick-a-transport}

| Transport | Was es ist | Wann |
|---|---|---|
| `stdio` | Der Host startet deine Datei als Subprozess und spricht über deren stdin und stdout. | Lokale Server. Der Standard. |
| `streamable-http` | Ein echter HTTP-Server, der auf einem Port lauscht. | Alles, was du bereitstellst. |
| `sse` | Der ältere HTTP-Transport. | Gar nicht. |

!!! warning
    SSE wurde in der Protokollrevision 2025-03-26 durch Streamable HTTP abgelöst.
    `mcp.run(transport="sse")` funktioniert weiterhin, mit eigenen Optionen `sse_path=` und `message_path=`,
    existiert aber nur für Clients, die noch nicht umgestiegen sind. Bau nichts Neues darauf.

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` ist synchron. Es blockiert, solange der Server lebt.
* Ohne Argument ist der Transport `stdio`.
* Es steht unter `if __name__ == "__main__":`, weil alles, was deinen Server lädt (`mcp dev`, `mcp run`, `mcp install`, deine Tests), diese Datei **importiert**. Der Guard verhindert, dass aus einem Import ein laufender Server wird.

### stdio {#stdio}

Es gibt nichts zu konfigurieren. Der Host startet deine Datei als Kindprozess, schreibt Requests in deren stdin und liest Responses von deren stdout.

Starte sie selbst, und du siehst die Konsequenz:

```console
python server.py
```

Nichts wird ausgegeben, und es kehrt nicht zurück. Der Prozess wartet auf stdin darauf, dass ein Host zuerst spricht.

Das heißt auch: stdout **ist die Leitung**. Während der Server läuft, verlegt das SDK die Leitung auf einen privaten Deskriptor und leitet Ausgaben, die nach stdout *geflusht* werden (ein Subprozess, der in sein geerbtes stdout schreibt, ein geflushtes `print()`), nach stderr um, wo sie den Stream nicht beschädigen können. Ausgaben, die *vor* dem Start des Servers nach stdout geflusht werden (ein Wrapper-Skript mit echo, ein ungepuffertes print zur Importzeit), landen trotzdem auf der Leitung – genauso ein `print()`, das gepuffert bleibt, bis der Interpreter den Puffer beim Beenden leert. Für Ausgaben, die du wirklich haben willst, ist das Modul `logging` das richtige Tool: Sein Handler flusht jeden Eintrag sofort nach stderr. Alles Weitere steht in **[Logging](../handlers/logging.md)**.

### Ausprobieren {#try-it}

```console
uv run mcp dev server.py
```

Der Inspector macht genau das, was ein echter Host macht: Er startet `server.py` als Subprozess und verbindet sich über stdio damit.

Du hast ihm nie einen Port gegeben. Es gibt keinen.

## Streamable HTTP {#streamable-http}

Um denselben Server stattdessen auf einen Port zu legen, nennst du den Transport (und seine Optionen) in `run()`:

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

Diese eine Zeile baut eine Starlette-App und liefert sie mit uvicorn aus. Clients verbinden sich mit `http://127.0.0.1:3001/mcp`.

Jeder Transport hat eigene Keyword-Argumente, alle an `run()`:

* `host` / `port`: wo gelauscht wird. Standardwerte `127.0.0.1` und `8000`.
* `streamable_http_path`: wo der MCP-Endpunkt liegt. Standardwert `/mcp`.
* `json_response=True`: jeden POST mit einem einzelnen JSON-Body statt eines SSE-Streams beantworten. Dieser Body hat Platz für die Response und sonst nichts. Ein Tool, das mitten im Request in den Client zurückruft (`ctx.elicit()`, Sampling), löst auf dieser Strecke daher `NoBackChannelError` aus, und Benachrichtigungen, die an den laufenden Aufruf gebunden sind (Fortschritt aus `ctx.report_progress()`, Log-Nachrichten pro Aufruf), werden verworfen; der eigenständige `GET`-Stream trägt davon unabhängige weiterhin.
* `stateless_http=True`: ein frischer Transport pro Request, kein Session-Tracking.
* `max_request_body_size`: größter akzeptierter POST-Body in Bytes. Standardwert 4 MiB; größere Requests
  erhalten HTTP 413, bevor geparst oder eine Session angelegt wird. Erhöhe ihn nur, wenn legitime MCP-Nachrichten
  diese Größe überschreiten.
* `event_store`, `retry_interval`, `transport_security`: Wiederaufnahme und Schutz vor DNS-Rebinding. Sie können warten, bis du anderswo als auf localhost bereitstellst; **[Bereitstellen und skalieren](deploy.md)** behandelt `transport_security`.

!!! warning
    Transport-Optionen gehen an `run()`, **nicht** an `MCPServer(...)`. Der Konstruktor beschreibt, was
    dein Server *ist*: Name, Version, Instruktionen. `run()` beschreibt, wie er ausgeliefert wird. Vertauschst du
    das, antwortet Python, bevor MCP überhaupt beteiligt ist:

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` ist der kurze Weg. Sobald du mehr brauchst (deinen Server in eine bestehende App eingehängt, zwei Server in einem Prozess, CORS für Browser-Clients), baust du die ASGI-App selbst und übergibst sie einem beliebigen ASGI-Host. Das ist **[Zu einer bestehenden App hinzufügen](asgi.md)**.

## Server-Einstellungen {#server-settings}

Ein paar Dinge rund ums Betreiben haben nichts mit dem Transport zu tun. Sie sind Konstruktor-Argumente:

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`: wird an `logging.basicConfig()` übergeben, sobald `MCPServer(...)` konstruiert wird. Das konfiguriert den **Root**-Logger und setzt damit das Level auch für deine eigenen Logger, nicht nur für die des SDK. Standardwert `"INFO"`.
* `debug`: wird an die Starlette-App weitergereicht, die die HTTP-Transporte bauen. Standardwert `False`.

Beide landen auf `mcp.settings`, das du zur Laufzeit zurücklesen kannst.

## Der Befehl `mcp` {#the-mcp-command}

Das Extra `[cli]` installiert ein kleines Kommandozeilen-Tool rund um all das.

`mcp dev` betreibt deinen Server unter dem **MCP Inspector**:

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` fügt der Umgebung, die es baut, Pakete hinzu; `--with-editable` installiert dein eigenes Paket hinein. Es braucht `npx` auf deinem `PATH`: Der Inspector ist eine Node.js-App.

`mcp run` importiert die Datei, findet das Server-Objekt (ein `mcp`, `server` oder `app` auf Modulebene) und ruft `run()` darauf auf:

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

Das Suffix mit `:` benennt das Objekt, wenn es nicht `mcp`, `server` oder `app` heißt.

Dein Block `if __name__ == "__main__":` wird hier nie ausgeführt: `mcp run` ruft `run()` selbst auf, und die einzige Option, die es weiterreicht, ist `--transport`.

`mcp install` registriert den Server bei **Claude Desktop**, sodass die App ihn für dich startet:

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` und `-f .env` halten Umgebungsvariablen in diesem Eintrag fest. Claude Desktop startet deinen Server in einem eigenen Prozess. Die Umgebung deiner Shell ist dort nicht vorhanden.

Claude Desktop ist der einzige Host, den `mcp install` kennt. Jeder andere Host (Claude Code, Cursor, VS Code) nimmt denselben Startbefehl in seiner eigenen Konfigurationsdatei entgegen, und **[Mit einem echten Host verbinden](../get-started/real-host.md)** hat jeden einzelnen.

`mcp version` gibt die installierte SDK-Version aus.

!!! tip
    `mcp dev` und `mcp run` verstehen nur `MCPServer`. Wenn du mit dem Low-Level-`Server` baust,
    betreibst du ihn selbst. Siehe **[Der Low-Level-Server](../advanced/low-level-server.md)**.

## Zusammenfassung {#recap}

* Ein **Transport** ist der Weg, auf dem Bytes deinen Server erreichen: `stdio` für einen lokalen Subprozess, `streamable-http` für einen Port. SSE ist abgelöst.
* `mcp.run()` wählt den Transport. Ohne Argument ist es `stdio`, und es blockiert.
* Jede Transport-Option (`host`, `port`, `streamable_http_path`, ...) ist ein Argument für `run()`, nie für `MCPServer(...)`.
* Lass `run()` unter `if __name__ == "__main__":`. Alles, was deinen Server lädt, importiert zuerst die Datei.
* `log_level=` und `debug=` sind Konstruktor-Argumente; sie landen auf `mcp.settings`.
* `mcp dev` für den Inspector, `mcp run` zum Ausführen einer Datei, `mcp install` für Claude Desktop, `mcp version` für die Version.
* Der Transport ändert nie, was dein Server *ist*: Alle drei Dateien auf dieser Seite stellen dasselbe Tool bereit.

Wenn `run()` selbst die Grenze ist (dein Server in einer App, die es schon gibt), geht es mit **[Zu einer bestehenden App hinzufügen](asgi.md)** weiter. Ein echter Hostname und mehr als ein Worker sind **[Bereitstellen und skalieren](deploy.md)**. Und wenn manche deiner Clients noch auf Spezifikationsversion 2025-11-25 oder älter sind, ist **[Legacy-Clients unterstützen](legacy-clients.md)** die gute Nachricht.
