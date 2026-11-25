---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "Diese Dokumentation beschreibt v2, die aktuelle stabile Release-Linie"
    Neu bei v2 oder kommst du von v1? **[Neu in v2](whats-new.md)** ist die Fünf-Minuten-Tour durch alle Änderungen, und der **[Migrationsleitfaden](migration.md)** behandelt jeden Breaking Change.
    Noch auf v1.x? Die Dokumentation dazu findest du in den [v1.x-Docs](https://py.sdk.modelcontextprotocol.io/v1/).
    Etwas hakt oder ist unklar? [Sag uns Bescheid](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml).

Mit dem **Model Context Protocol (MCP)** können Anwendungen LLMs auf standardisierte Weise Kontext bereitstellen. Dabei wird das *Bereitstellen* von Kontext von der eigentlichen Interaktion mit dem LLM getrennt.

Dies ist das offizielle Python SDK dafür. Damit kannst du:

* **MCP-Server bauen**, die jedem MCP-Host Tools, Ressourcen und Prompts anbieten.
* **MCP-Clients bauen**, die sich mit jedem MCP-Server verbinden.
* Jeden Standard-Transport sprechen: stdio, Streamable HTTP und SSE.

## Voraussetzungen {#requirements}

Python 3.10+.

## Installation {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

Das Extra `[cli]` bringt den Befehl `mcp` mit; den brauchst du für die Entwicklung.
Wofür die einzelnen Abhängigkeiten da sind, steht unter [Installation](get-started/installation.md).

## Beispiel {#example}

### Erstellen {#create-it}

Lege eine Datei `server.py` an:

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

Das ist ein vollständiger MCP-Server.

Er bietet ein **Tool** an, `add`, und eine **Ressource** mit Template, `greeting://{name}`.

### Starten {#run-it}

```console
uv run mcp dev server.py
```

Das startet deinen Server und öffnet den [MCP Inspector](https://github.com/modelcontextprotocol/inspector), eine interaktive Oberfläche, mit der du ihn erkunden kannst. Öffne die URL, die er ausgibt.

!!! note
    Der Inspector ist eine Node.js-App, deshalb braucht `mcp dev` `npx` auf deinem `PATH`.

### Ausprobieren {#try-it}

Gehe im Inspector zu **Tools** und rufe `add` mit `a=1`, `b=2` auf.

Du bekommst `3` zurück. ✨

Dieses Formular (ein Pflichtfeld vom Typ Integer für `a`, ein weiteres für `b`) hat der Inspector aus deinen Type Hints gebaut. Claude macht das genauso, und jeder andere MCP-Host auch.

Gehe jetzt zu **Resources** und lies `greeting://World`:

```text
Hello, World!
```

### Zusammenfassung {#recap}

Sieh dir noch einmal an, was du **nicht** geschrieben hast:

* Kein JSON Schema. `a: int, b: int` *ist* das Schema.
* Kein Parsen von Requests, keine Serialisierung, kein Validierungscode.
* Keinerlei Protokollbehandlung.

Du hast zwei Python-Funktionen mit Type Hints und einem Docstring geschrieben. Den Rest erledigt das SDK.

## Wie es weitergeht {#where-to-go-next}

* **[Einstieg](get-started/index.md)** führt dich von der Installation zu einem funktionierenden, getesteten Server.
* Du baust eine Anwendung, die MCP-Server *nutzt*? Beginne mit **[Clients](client/index.md)**.
* Du hast schon eine FastAPI- oder Starlette-App? **[In eine bestehende App einbinden](run/asgi.md)** hängt einen MCP-Server darin ein.
* Du suchst eine bestimmte Fehlermeldung? **[Fehlerbehebung](troubleshooting.md)** ist nach dem wörtlichen Text geordnet.
* Du fragst dich, was sich in v2 geändert hat? **[Neu in v2](whats-new.md)** ist die Fünf-Minuten-Tour.
* Du migrierst von v1? Beginne mit dem **[Migrationsleitfaden](migration.md)**.
* Du suchst eine genaue Signatur? Die **[API-Referenz](api/mcp/index.md)** wird aus dem Quellcode generiert.
* Du liest mit einem LLM? Diese Dokumentation wird auch im Format [llms.txt](https://llmstxt.org/) veröffentlicht:
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) ist ein Index der Seiten, und
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) enthält alle Seiten in einer einzigen Datei.
