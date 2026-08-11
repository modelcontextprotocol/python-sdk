---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

Eine **MCP App** ist ein Tool mit Gesicht: Neben seinen Daten verweist das Tool auf ein HTML-Dokument, das der Host als interaktive Oberfläche rendert.

Zwei Teile, immer zwei Teile:

1. **Ein Tool**, das die Arbeit macht und Daten zurückgibt, wie jedes andere Tool auch.
2. **Eine `ui://`-Ressource** mit dem HTML, das der Host dafür anzeigt.

Das Tool trägt eine `_meta.ui.resourceUri`-Referenz auf die Ressource. Der Host holt sie mit `resources/read`, rendert sie in einem **Sandbox-iframe** und schiebt das Ergebnis des Tools per `postMessage` in diesen iframe. Dein Server sendet oder empfängt niemals `ui/*`-Nachrichten: Dieser Verkehr läuft zwischen Host und iframe. Du lieferst ein Tool und ein HTML-Dokument; das Theater übernimmt der Host.

Das SDK liefert das als eingebaute Extension `Apps` (`io.modelcontextprotocol/ui`) mit. Falls [Extensions](extensions.md) neu für dich sind, überfliege zuerst jene Seite. Eine Minute, dann komm zurück.

## Eine Uhr mit Gesicht {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

Vier Schritte:

* `Apps()`: Eine Instanz hält deine UI-gebundenen Tools und ihre Ressourcen.
* `@apps.tool(resource_uri="ui://clock/app.html")`: ein normales Tool plus der `_meta.ui.resourceUri`-Stempel. Alles, was `@mcp.tool()` akzeptiert (name, title, description, ...), wird durchgereicht.
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: die passende Ressource, ausgeliefert als `text/html;profile=mcp-app`. Genau dieser MIME-Typ sagt einem Host „das ist eine App, rendere sie“.
* `MCPServer("clock", extensions=[apps])`: die Anmeldung. Der Server bewirbt jetzt `io.modelcontextprotocol/ui` unter `capabilities.extensions`.

Das HTML selbst lauscht auf das `postMessage` des Hosts und zeigt das Ergebnis an. Für echte Apps verwende das offizielle Browser-SDK [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps) in deinem HTML. Es gibt dir `ontoolresult`, `callServerTool`, `getHostContext` und `onhostcontextchanged` statt roher Message-Events.

## Graceful Degradation {#graceful-degradation}

Nicht jeder Client rendert Apps. Die Spezifikation sagt unverblümt, was das für dich bedeutet:

> Tools **MÜSSEN** ein sinnvolles `content`-Array zurückgeben, auch wenn eine UI verfügbar ist.

Das Modell liest `content`; der iframe ist für Menschen. Ein UI-fähiger Host füttert das Modell trotzdem mit dem Textergebnis, und ein reiner Text-Client bekommt *nur* das. Das kanonische Muster ist also: ein Tool, zwei Antworten. Sieh dir `get_time` noch einmal an:

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` ist nur dann `True`, wenn der Client die Extension `io.modelcontextprotocol/ui` deklariert **und** `text/html;profile=mcp-app` in seinen `mimeTypes`-Einstellungen aufgeführt hat. Das Feld ist Pflicht, ein Client, der es weglässt, zählt also nicht. Genau das deklariert `main()` in derselben Datei: die Client-Hälfte der Aushandlung – und die reichhaltige Antwort kommt zurück.

!!! warning
    Gib niemals einen Platzhalter wie `"[Rendered UI]"` als einzigen Inhalt zurück. Wenn der Fallback-Text nutzlos ist, ist das Tool für jeden reinen Text-Client und für das Modell selbst nutzlos. Schreib den Satz.

## Den iframe abriegeln {#locking-the-iframe-down}

Die Ressourcenseite trägt die Sicherheitsmetadaten: was der iframe laden darf, welche Browser-Berechtigungen er möchte, wie er eingebettet werden will:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` und `permissions` sind **Anfragen an den Host**, kein Serververhalten. Der Host baut daraus die Content-Security-Policy und die Permissions-Policy des iframes, und er darf ablehnen. Prüfe in deinem JS per Feature Detection, statt eine Zusage vorauszusetzen.

`ResourceCsp`, Feld für Feld (Python-Name, Schlüssel auf der Leitung, was der Host damit macht):

| Python | Leitung (`_meta.ui.csp`) | Steuert |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: wohin `fetch`/XHR gehen darf |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: statische Assets |
| `frame_domains` | `frameDomains` | `frame-src`: verschachtelte iframes |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: worauf `<base>` zeigen darf |

`ResourcePermissions`: Jedes Feld fordert eine Browser-Berechtigung für den iframe an.

| Python | Leitung (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP und Berechtigungen liegen auf der **Ressource**, nie auf dem Tool. Die Tool-Metadaten der Spezifikation haben keinen Platz dafür, und Hosts ignorieren sie dort. Das SDK macht den Fehler unmöglich: `@apps.tool()` hat schlicht keinen Parameter `csp`.

### Sichtbarkeit {#visibility}

`visibility=["app"]` an einem Tool sagt „das existiert für den iframe, nicht für das Modell“:

* `"model"`: Das Modell darf es aufrufen.
* `"app"`: Der iframe darf es aufrufen (über `callServerTool`).
* Weggelassen: beide, das ist der Standardwert.

Filtern ist Aufgabe des **Hosts**. Dein Server listet reine App-Tools in `tools/list` wie alle anderen; der Host verbirgt sie vor dem Modell. Filtere nicht serverseitig.

## Die Regeln, die das SDK durchsetzt {#the-rules-the-sdk-enforces}

All das schlägt beim Start fehl, nicht in Produktion:

* Ein `resource_uri` oder ein Ressourcen-URI, der nicht `ui://...` ist, ist ein `ValueError` zum Zeitpunkt der Dekoration bzw. Registrierung.
* Ein Tool, das an einen URI **ohne passende registrierte Ressource** gebunden ist, ist ein `ValueError`, wenn `MCPServer(extensions=[apps])` die Extension übernimmt. Ein Tool, das HTML bewirbt, das bei `resources/read` mit 404 antwortet, ist eine Fehlkonfiguration, also verweigert der Server die Konstruktion.
* `meta={"ui": ...}` an `@apps.tool()` ist ein `ValueError`. `_meta["ui"]` gehört dem Dekorator; sag es mit `resource_uri=` und `visibility=`. Andere `meta=`-Schlüssel werden daneben problemlos zusammengeführt.

Weder das TypeScript-ext-apps-SDK noch FastMCP fängt heute irgendetwas davon ab; uns ist lieber, du erfährst es, bevor ein Host es tut.

## Über Inline-HTML hinaus {#beyond-inline-html}

`add_html_resource` deckt den häufigen Fall ab: einen String mit HTML. Für alles andere, HTML auf der Platte oder generierte Inhalte, baust du die Ressource selbst und reichst sie weiter:

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

`add_resource` ergänzt den MIME-Typ `text/html;profile=mcp-app`, wenn die Ressource keinen explizit setzt, und weist einen expliziten Widerspruch zurück: Eine `ui://`-Ressource unter einem anderen MIME-Typ rendert kein Host.

!!! tip
    Du zielst auf einen Pre-GA-Host, der noch den veralteten flachen Schlüssel `_meta["ui/resourceUri"]` liest? Führe ihn selbst zusammen:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`.
    Das verschachtelte `ui`-Objekt ist die Form der Spezifikation; der flache Schlüssel ist auf dem Weg nach draußen.

## Laufen sehen {#see-it-run}

Die Story `apps` in `examples/stories/` ist diese Seite als lauffähiges Paar: ein Server mit einem UI-gebundenen Uhr-Tool und ein Client, der Apps aushandelt, die `_meta.ui.resourceUri` des Tools liest, das HTML holt und das Tool aufruft.

```bash
uv run python -m stories.apps.client
```
