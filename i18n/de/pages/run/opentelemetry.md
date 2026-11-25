---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

Dein Server wird bereits getract. Du musst nichts hinzufügen.

Jeder Server, den du erzeugst, gibt für jede Nachricht, die er verarbeitet, einen [OpenTelemetry](https://opentelemetry.io/)-Span aus. Das hast du nicht geschrieben, und du importierst es auch nicht. Es ist da, sobald du `MCPServer(...)` aufrufst.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

Das ist ein vollständiger Server mit Tracing. Ruf `search_books` auf, und dafür entsteht ein Span. Dasselbe gilt für den Low-Level-`Server`: Das Tracing lebt auf beiden.

## Was du bekommst {#what-you-get}

Jede eingehende Nachricht wird zu einem `SERVER`-Span, benannt nach der Methode und ihrem Ziel. Ein `tools/call` für `search_books` ist also der Span `tools/call search_books`, und ein bloßes `tools/list` ist einfach `tools/list`.

Jeder Span trägt ein paar Attribute:

* `mcp.method.name` und `mcp.protocol.version`, auf jedem Span.
* `jsonrpc.request.id`, auf einem Request (eine Benachrichtigung hat keine).
* Ein Handler, der eine Exception auslöst, setzt den Span-Status auf Fehler. Ein Tool-Ergebnis mit `is_error=True` tut das ebenfalls.

Und weil das Tracing eines Tool-Aufrufs so oft gewünscht ist, sprechen `tools/call`-Spans die [GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) von OpenTelemetry:

* `gen_ai.operation.name`, gesetzt auf `"execute_tool"`.
* `gen_ai.tool.name`, gesetzt auf das aufgerufene Tool.

Ein `prompts/get`-Span bekommt im selben Sinne `gen_ai.prompt.name`. Die List-Methoden tragen keine `gen_ai.*`-Schlüssel, weil es dort nichts zu benennen gibt.

!!! tip
    Diese GenAI-Attribute sind der Grund, warum eine Tracing-Oberfläche deine Tool-Aufrufe so gruppiert, wie sie die jedes anderen Agenten gruppiert. Diese Gruppierung bekommst du umsonst, ohne zusätzlichen Code.

## Kostenlos, bis du es brauchst {#it-costs-nothing-until-you-want-it}

Hier kommt der Teil, der „standardmäßig an“ zu einem angenehmen Standard macht.

Das SDK hängt nur von `opentelemetry-api` ab, der leichtgewichtigen Hälfte von OpenTelemetry. Ohne installiertes SDK und ohne Exporter ist das Erzeugen eines Spans ein No-op. Die Spans, die dein Server gerade ausgibt, kosten dich also fast nichts, und niemand sammelt sie ein.

An dem Tag, an dem du sie *sehen* willst, installierst du die andere Hälfte und richtest sie auf ein Ziel:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

Konfiguriere einen Exporter auf die übliche OpenTelemetry-Weise, und jeder Span, den das SDK bisher still erzeugt hat, leuchtet auf. Dein Server-Code ändert sich nicht. Keine einzige Zeile.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) ist ein solches Backend, und es übernimmt die Konfiguration für dich: `pip install logfire`, `logfire.configure()`, und deine MCP-Spans erscheinen in der Live-Ansicht. Es baut auf OpenTelemetry auf, deshalb gilt alles Folgende auch dafür.

## Traces, die über die Leitung gehen {#traces-that-cross-the-wire}

Ein Trace ist am nützlichsten, wenn er einem Request vom Client in den Server folgt, in einem zusammenhängenden Bild.

Wenn Client und Server beide das SDK einsetzen, entsteht diese Verbindung automatisch. Der Client fügt den [W3C Trace Context](https://www.w3.org/TR/trace-context/) in den Request ein, und der Server liest ihn wieder aus, sodass der Server-Span im selben Trace unter dem Client-Span eingeordnet wird. Das ist [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414), und du bekommst es, ohne danach zu fragen.

Trägt die eingehende Nachricht keinen Trace Context – zum Beispiel ein Request von einem Client, der nicht das SDK ist –, hängt sich der Server-Span einfach an den Span, der auf dem Server gerade aktuell ist, statt einen brandneuen, verwaisten Trace zu beginnen.

## Abschalten {#turning-it-off}

Das Tracing ist eine Middleware, die erste in der Liste deines Servers. Wenn du wirklich einen Server willst, der keine Spans ausgibt, nimm sie heraus:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    Dieser Import hat einen führenden Unterstrich, und das ist Absicht. Die Klasse ist vorläufig, so wie [`Server.middleware`](../advanced/middleware.md) vorläufig ist, deshalb solltest du damit rechnen, dass sich der Importpfad ändert. Du brauchst das fast nie: Ohne installierten Exporter sind die Spans kostenlos, die übliche Antwort ist also, sie eingeschaltet zu lassen und keinen Exporter zu installieren.

## Zusammenfassung {#recap}

* Jeder `MCPServer` und jeder Low-Level-`Server` gibt ohne weitere Konfiguration pro eingehender Nachricht einen `SERVER`-Span aus. Du schreibst nichts.
* Spans tragen `mcp.method.name` und `mcp.protocol.version`; `tools/call` und `prompts/get` tragen zusätzlich GenAI-Attribute, sodass deine Tool-Aufrufe gruppiert werden wie die jedes anderen Agenten.
* Es kostet nichts, bis du ein OpenTelemetry-SDK und einen Exporter installierst, und dann leuchtet es auf, ohne dass sich dein Server ändert.
* Der Trace Context vom Client zum Server wird automatisch weitergegeben, wenn beide Seiten das SDK einsetzen.

Was entscheidet, ob ein Request überhaupt läuft, ist die **[Autorisierung](authorization.md)**.
