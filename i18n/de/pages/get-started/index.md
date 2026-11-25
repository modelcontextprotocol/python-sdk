---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# Einstieg {#get-started}

Neu bei MCP oder neu bei diesem SDK? Fang hier an. Diese Seiten bringen dich von null zu einem
funktionierenden, getesteten Server: [das SDK installieren](installation.md), den
[ersten Server](first-steps.md) bauen, [ihn mit einem echten Host verbinden](real-host.md) und
[ihn testen](testing.md) – mit einem In-Memory-Client.

## Den Code ausführen {#run-the-code}

Alle Codeblöcke lassen sich direkt kopieren und verwenden: Es sind vollständige, lauffähige Dateien.

Um mitzumachen, füge einen Block in eine `server.py` ein und öffne sie im MCP Inspector:

```console
uv run mcp dev server.py
```

Es wird **DRINGEND empfohlen**, den Code selbst zu schreiben (oder zu kopieren), ihn zu bearbeiten und lokal auszuführen. Erst im eigenen Editor zeigt sich, worum es geht: wie wenig du schreibst, die Autovervollständigung, die Typprüfungen, die Fehler abfangen, bevor du überhaupt etwas ausführst.

## Kein Rätselraten {#you-will-not-be-guessing}

Jedes Beispiel in dieser Dokumentation ist eine vollständige Datei unter [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) im Repository des SDK selbst, und jedes einzelne wird von der Testsuite des SDK über einen **In-Memory-Client** ausgeführt:

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

Kein Subprozess, kein Port, kein Transport. `Client(mcp)` verbindet sich direkt mit dem Server-Objekt.

Wenn eine Änderung am SDK ein Beispiel auf einer dieser Seiten kaputt macht, wird die CI rot, bevor es die Seite tut. Der Code, den du hier liest, ist der Code, der läuft.

Das wirst du in [Testen](testing.md) selbst verwenden; so testest du auch deine eigenen Server.

## Wie es weitergeht {#where-to-go-next}

Sobald ein Server läuft, ist der Rest dieser Dokumentation ein Nachschlagewerk, kein Kurs.
Jede Seite steht für sich, spring also direkt zu dem, was du brauchst:

* Was ein Server bereitstellt (Tools, Ressourcen, Prompts), steht in **[Server](../servers/index.md)**.
* Was innerhalb der Funktionen, die du registrierst, verfügbar ist, steht in **[Im Handler](../handlers/index.md)**.
* Wie du ihn vor Clients bringst (stdio, HTTP, deine bestehende FastAPI-App), steht in **[Den Server betreiben](../run/index.md)**.
* Wie du die andere Seite baust, eine Anwendung, die MCP-Server *nutzt*, steht in **[Clients](../client/index.md)**.
