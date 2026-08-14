---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# Testen {#testing}

Das Python SDK bringt eine Klasse `Client` mit einem **In-Memory-Transport** mit: Übergib ihr dein Server-Objekt, und sie verbindet sich direkt damit.

Kein Subprozess. Kein Port. Überhaupt kein Transport. Die Idee ist dieselbe wie bei FastAPIs `TestClient`.

## Grundlegende Verwendung {#basic-usage}

Nehmen wir an, du hast einen einfachen Server mit einem einzigen Tool:

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

Um den Test unten auszuführen, brauchst du zwei zusätzliche (Entwicklungs-)Abhängigkeiten:

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    Diese Dokumentation geht davon aus, dass du [`pytest`](https://docs.pytest.org/en/stable/) bereits kennst.

    [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) nutzt der Test unten,
    um in einer Zeile auf das gesamte Ergebnisobjekt zu prüfen. Es zeichnet die Ausgabe eines Tests
    als das `snapshot(...)`-Literal auf, das du siehst. Wenn du es lieber nicht verwenden möchtest,
    lass den Import weg und prüfe die Felder, die dich interessieren (`result.content[0].text == "3"`),
    wie in jedem anderen Test.

Jetzt der Test:

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. Wenn du `trio` verwendest, gib stattdessen `"trio"` zurück. Die Details stehen in der [anyio-Dokumentation](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on).
2. Das Fixture liefert einen verbundenen Client. Jeder Test, der `client` entgegennimmt, bekommt eine frische In-Memory-Verbindung zum selben Server.

Das war's. Jetzt kannst du deine Tests um weitere Szenarien erweitern.

## Warum `raise_exceptions=True`? {#why-raise_exceptionstrue}

Zwei verschiedene Dinge können schiefgehen, und dieses Flag betrifft nur eines davon.

Eine Exception in einem **deiner Tools** ist kein Protokollfehler. Sie wird zu einem normalen Ergebnis mit
`is_error=True`, und das Modell liest die Meldung. `raise_exceptions` ändert daran nichts: Mit oder
ohne das Flag gibt `call_tool` dasselbe Ergebnis mit `is_error=True` zurück. Dazu gibt es eine ganze Seite:
**[Fehler behandeln](../servers/handling-errors.md)**.

Ein Fehler **außerhalb** eines Tool-Bodys ist etwas anderes. Auf der Verbindung, die dir `Client(mcp)` gibt,
bereinigt der Server ihn zu einem allgemeinen `"Internal server error"`, bevor der Client ihn sieht. Du solltest
die Details eines unerwarteten Absturzes niemals an einen entfernten Aufrufer durchsickern lassen. In einem Test ist das
genau das, was du *nicht* willst, und genau das ändert `raise_exceptions=True`: Dein Test sieht die echte Meldung
statt der bereinigten.

Lass es in Tests eingeschaltet. In Produktionscode hat es keine Bedeutung.

## Standardmäßig im selben Prozess {#in-process-by-default}

!!! note
    `Client(mcp)` verbindet sich im selben Prozess und ist standardmäßig **generationsneutral** (era-neutral): Er prüft den Server und
    wählt den passenden Protokollpfad. Lege `mode="legacy"` fest, wenn dein Test Legacy-spezifische
    Semantik prüft (Sampling- oder Elicitation-Push – Elicitation ist die Rückfrage bei der Person am Host –, `message_handler`), und lass `raise_exceptions=True`
    dort weg: Eine Legacy-Verbindung bereinigt von vornherein nie, und das Flag löst den
    Fehler erneut in der Server-Task aus statt in deinem Test.

Diese eine Zeile ist auch der Grund, warum diese Dokumentation dir versprechen kann, dass ihre Beispiele funktionieren: Jede
Beispieldatei wird von der Test-Suite des SDK selbst ausgeführt, fast alle über genau diesen
Client. Du verwendest dasselbe Tool, das das SDK auf sich selbst anwendet.

Du hast einen funktionierenden, getesteten Server. Wie du ihn in eine echte Anwendung (Claude Desktop, eine
IDE) einbindest, steht in **[Mit einem echten Host verbinden](real-host.md)**; jede andere Art, ihn zu betreiben, in
**[Den Server betreiben](../run/index.md)**.
