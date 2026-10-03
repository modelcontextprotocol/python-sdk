---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# Installation {#installation}

Das Python-SDK liegt auf PyPI als [`mcp`](https://pypi.org/project/mcp/). Es setzt **Python 3.10+** voraus.

Diese Dokumentation beschreibt **v2**, die aktuelle stabile Release-Linie:

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "Umstieg von v1?"
    v2 ist eine Hauptversion mit inkompatiblen Änderungen; der **[Migrationsleitfaden](../migration.md)**
    behandelt jede einzelne davon. Wenn dein *Paket* von `mcp` abhängt und noch nicht bereit für die
    Migration ist, behalte eine Obergrenze `<2` bei (zum Beispiel `mcp>=1.28,<2`), damit eine nicht
    gepinnte Auflösung auf der 1.x-Linie bleibt.

## Was installiert wird {#what-gets-installed}

Nichts davon musst du wissen, um das SDK zu nutzen. Falls du dich aber fragst, wozu die einzelnen Abhängigkeiten da sind:

* `mcp-types`: jeder Protokolltyp (Requests, Ergebnisse, Content-Blöcke) als eigenes Paket, im Gleichschritt mit dem SDK versioniert. Code, der von `mcp` abhängt, importiert es über den Alias `mcp.types` (jedes `from mcp.types import ...` in dieser Dokumentation); importiere `mcp_types` nur in einem Projekt direkt, das `mcp-types` ohne das SDK installiert.
* [`anyio`](https://anyio.readthedocs.io/): die asynchrone Laufzeit. Das gesamte SDK ist gegen anyio geschrieben und läuft daher sowohl auf `asyncio` als auch auf `trio`.
* [`pydantic`](https://docs.pydantic.dev/): die Grundlage jedes `mcp.types`-Modells, dazu die gesamte Schema-Generierung und Validierung.
* [`httpx2`](https://pypi.org/project/httpx2/): der HTTP-Client hinter den *Client*-Transporten für Streamable HTTP und SSE, mit eingebauter Unterstützung für Server-Sent Events.
* [`starlette`](https://www.starlette.io/), [`uvicorn`](https://www.uvicorn.org/), [`sse-starlette`](https://pypi.org/project/sse-starlette/) und [`python-multipart`](https://pypi.org/project/python-multipart/): die *Server*-Transporte für HTTP.
* [`jsonschema`](https://pypi.org/project/jsonschema/): validiert die strukturierte Ausgabe eines Tools gegen das deklarierte Output-Schema.
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/): Verarbeitung von OAuth-Tokens für die Autorisierung.
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/): nur die schlanke API. Die Tracing-Middleware des SDK kostet also nichts, solange du nicht selbst ein OpenTelemetry-SDK samt Exporter installierst.
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) und [`typing-inspection`](https://pypi.org/project/typing-inspection/): moderne Typing-Features auf Python 3.10.
* [`pywin32`](https://pypi.org/project/pywin32/): nur unter Windows, für die Verwaltung von `stdio`-Subprozessen.

## Optionale Extras {#optional-extras}

* `mcp[cli]` ergänzt [`typer`](https://typer.tiangolo.com/) und [`python-dotenv`](https://pypi.org/project/python-dotenv/) für das Kommandozeilen-Tool `mcp` (`mcp dev`, `mcp run`, `mcp install`). Während der Entwicklung wirst du das haben wollen; in einem bereitgestellten Server brauchst du es womöglich nicht.
* `mcp[rich]` ergänzt [`rich`](https://rich.readthedocs.io/) für schönere Server-Logs.
