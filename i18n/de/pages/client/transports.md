---
translation:
  sections: [9cac816674181eb0, 7c157764133fea1f, 40b4916d82eaf1d4, 10d151f2cc75317f, 3d0832f39b0d7059, 92742ba36533633d, 0aeca6145e7bd302]
  tool: 1
---
# Client-Transporte {#client-transports}

Jeder `Client` spricht mit seinem Server über einen **Transport**: das, was die Nachrichten tatsächlich befördert.

Du konfigurierst nie einen separat. `Client` nimmt ein einziges positionales Argument und leitet den Transport aus dessen Typ ab.

Die *Server*-Seite jedes Transports (was `mcp.run()` tut und was du bereitstellst) steht in **[Den Server betreiben](../run/index.md)**.

## Streamable HTTP {#streamable-http}

Übergib einen URL-String und du bekommst **Streamable HTTP** – den Transport, hinter dem du bereitstellst und zu dem du zuerst greifen solltest:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

Das ist der ganze Produktions-Client. `Client` packt die URL für dich in `streamable_http_client(...)`, auf Basis eines `httpx2.AsyncClient`, der so konfiguriert ist, wie MCP es braucht: ein Timeout von 30 Sekunden für connect/write/pool und ein Read-Timeout von 300 Sekunden, weil der Server einen Response-Stream offen halten kann.

!!! check
    Ein `Client`, den du erzeugt hast, ist **nicht** verbunden. Das Erzeugen wählt nur den Transport;
    erst `async with` öffnet ihn. Greifst du vor dem Eintreten auf die Verbindung zu, sagt dir das SDK das:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    Nichts wurde aufgelöst, abgerufen oder gestartet, als du `Client("http://...")` geschrieben hast. Diese Zeile kostet nichts.

### Einen eigenen `httpx2.AsyncClient` mitbringen {#bring-your-own-httpx2asyncclient}

Sobald du einen `Authorization`-Header, ein Cookie, einen Proxy, mTLS oder ein anderes Timeout brauchst, baust du den `httpx2.AsyncClient` selbst und übergibst ihn an `streamable_http_client`:

```python title="client.py" hl_lines="8-13"
--8<-- "docs_src/client_transports/tutorial003.py"
```

Zwei Dinge fallen auf:

* Der `httpx2.AsyncClient` gehört dir, also betrittst und verlässt **du** ihn. Das SDK schließt nie einen Client, den es nicht selbst erzeugt hat.
* `streamable_http_client(url, http_client=...)` gibt einen Transport zurück, und `Client(transport)` nimmt ihn an wie alles andere auch.

Eine Anmerkung zu TLS: `httpx2` prüft Zertifikate gegen den Trust Store des Betriebssystems (über
[`truststore`](https://pypi.org/project/truststore/)), nicht gegen eine mitgelieferte CA-Liste. In einer Umgebung ohne
nutzbaren System-CA-Store (manche minimalen Container) setzt du die Standard-Umgebungsvariablen `SSL_CERT_FILE`/`SSL_CERT_DIR`
oder übergibst deinem `httpx2.AsyncClient` ein explizites `verify=ssl_context`
(Hintergrund in
[`httpx` und `httpx-sse` durch `httpx2` ersetzt](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)).

!!! warning
    `streamable_http_client` nahm früher `headers=` und `timeout=` direkt entgegen. Das tut er nicht mehr:
    seine einzigen Parameter sind `url`, `http_client` und `terminate_on_close`. Greifst du aus
    Gewohnheit zu `headers=`, bekommst du:

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    Alles, was mit HTTP zu tun hat, lebt jetzt auf dem einen `httpx2.AsyncClient`, den du übergibst.

!!! info
    `httpx2` behält die vertraute `httpx`-API bei. Wenn du `httpx` kennst, weißt du hier also bereits, wie Auth,
    Proxys, Event-Hooks, Retries und Verbindungslimits gehen. Das SDK fügt nichts hinzu und nimmt
    nichts weg – außer bei der [Behandlung von Redirects](#redirects). Hier dockt auch OAuth an:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. Der ganze Ablauf steht in **[OAuth-Clients](oauth-clients.md)**.

### Redirects {#redirects}

Der Transport verbindet sich mit der URL, die du ihm gegeben hast, und nur mit diesem Origin.

* Einem `307`/`308`-Redirect, der auf demselben Schema, Host und Port bleibt, wird gefolgt, ebenso `http://` → `https://` auf demselben Host. Das deckt den üblichen Trailing-Slash-Redirect `/mcp` → `/mcp/` ab.
* Einem Redirect irgendwo anders hin wird **nicht** gefolgt. Der Aufruf schlägt fehl mit:

    ```text
    MCPError: Redirect to https://other.example.com/mcp not followed; use that URL as the endpoint if it is the intended server
    ```

    Ist diese URL der Server, den du meintest, trag sie in deine Konfiguration ein. Wenn nicht, ist der Server oder ein Proxy davor falsch konfiguriert.

Das gilt für jeden `httpx2.AsyncClient`, den du übergibst: Seine Einstellung `follow_redirects` wird für MCP-Requests nicht herangezogen, in keine der beiden Richtungen. Die OAuth-Provider des SDK wenden dieselbe Regel auf ihre eigenen Requests an.

!!! tip
    `Redirect to http://… not followed: it would downgrade this HTTPS endpoint to plain HTTP` bedeutet, dass der
    Server hinter einem TLS-terminierenden Proxy sitzt, von dem er nichts weiß, und `http://`-Redirects ausgibt.
    Das behebst du auf dem Server (**[Bereitstellen und skalieren](../run/deploy.md#behind-a-tls-terminating-proxy)**)
    oder indem du genau die `https://…/`-URL verwendest, die die Meldung vorschlägt.

## stdio {#stdio}

Ein **stdio**-Server ist ein Subprozess. Der Client startet ihn, schreibt JSON-RPC in seine stdin und liest JSON-RPC aus seiner stdout. So betreibt ein Desktop-Host einen Server auf deinem Rechner: Ein Host *ist* dieser Code plus eine UI, und **[Mit einem echten Host verbinden](../get-started/real-host.md)** zeigt dieselbe Beziehung von der Seite des Hosts, als Konfigurationsdatei.

Beschreibe den Prozess mit `StdioServerParameters` und übergib das Objekt an `Client`:

```python title="client.py" hl_lines="3-7 11"
--8<-- "docs_src/client_transports/tutorial004.py"
```

Beim Eintreten in den Block wird der Prozess gestartet. Beim Verlassen wird der Subprozess beendet: stdin schließen, warten, abschießen, falls er hängen bleibt. Du räumst ihn nie selbst auf.

Die stderr des Kindprozesses landet in deiner. Um sie woandershin zu leiten, baust du den Transport selbst mit `stdio_client` (aus `mcp`) und übergibst stattdessen diesen: `Client(stdio_client(server, errlog=log_file))`.

!!! warning
    Der Kindprozess erbt **nicht** deine Umgebung. Er bekommt eine minimale Allow-List (`HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` und `USER` auf POSIX), damit nichts Sensibles in einen Prozess durchsickert, den du
    vielleicht nicht selbst geschrieben hast.

    Ein Server, der einen API-Key braucht, findet ihn dort nicht. Übergib ihn explizit mit `env=`; diese
    Variablen werden über die Allow-List gelegt. Genau das tut `BOOKSHOP_API_KEY` oben.

## Im Speicher {#in-memory}

In einem Test gibt es nichts bereitzustellen und nichts zu starten. Übergib das Server-Objekt selbst:

```python hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

Kein Subprozess, kein Port, keine Bytes auf einer Leitung. Client und Server sind zwei Objekte im selben Prozess, und der Aufruf läuft trotzdem durch die echte Protokollschicht: `search_books` wird genau so aufgelistet, validiert und aufgerufen, wie es über HTTP geschähe. **[Testen](../get-started/testing.md)** baut das ganze Muster darauf auf.

Dieselbe Form dient zugleich als Embedding-API: Eine Anwendung, die den Server selbst erzeugt, kann dessen Tools ohne Netzwerk-Hop aufrufen.

## SSE {#sse}

`sse_client(url)` aus `mcp.client.sse` ist der HTTP-Transport, den Streamable HTTP abgelöst hat. Pack ihn genauso ein, `Client(sse_client("http://localhost:8000/sse"))`, um mit einem Server zu sprechen, der ihn noch verwendet – und bau nichts Neues darauf.

## Das `Transport`-Protokoll {#the-transport-protocol}

Für `Client` ist alles oben Genannte dasselbe.

Ein **Transport** ist ein beliebiger asynchroner Kontextmanager, der ein `(read, write)`-Paar von Nachrichten-Streams liefert: formal das `Transport`-Protokoll in `mcp.client`. `Client` löst sein Argument nach Typ auf: Ein `str` wird zu `streamable_http_client(url)`, ein `StdioServerParameters` wird zu `stdio_client(params)`, ein Server-Objekt verbindet im Prozess, und alles andere wird direkt als Transport betreten. Diese letzte Regel ist der Grund, warum `stdio_client(...)`, `streamable_http_client(...)` und `sse_client(...)` alle in denselben Platz passen – und warum du deinen eigenen schreiben kannst.

## Zusammenfassung {#recap}

* `Client("http://.../mcp")` (eine URL) verbindet über Streamable HTTP, den Produktions-Transport.
* Header, Auth, Proxys und Timeouts gehören auf einen `httpx2.AsyncClient`, den du an `streamable_http_client(url, http_client=...)` übergibst. Es gibt kein Keyword `headers=`.
* Redirects wird nur innerhalb des eigenen Origins der URL gefolgt (ein Trailing-Slash-`307`/`308`), plus `http`→`https` auf demselben Host. Alles andere schlägt mit `Redirect to … not followed` fehl; konfiguriere die endgültige URL.
* stdio ist `Client(StdioServerParameters(...))`. Pack es nur dann selbst in `stdio_client(...)` ein, wenn du die stderr des Kindprozesses umleiten willst.
* Der Subprozess bekommt eine Umgebung per Allow-List, nicht deine; `env=` ergänzt sie.
* `Client(mcp)` (das Server-Objekt) verbindet im Speicher. Nutze es in Tests oder um einen Server in die Anwendung einzubetten, die ihn gebaut hat.
* Ein Transport ist alles, womit du `async with x as (read, write)` schreiben kannst. Alles, was weder Server-Objekt noch URL noch `StdioServerParameters` ist, reicht `Client` direkt an dieses Protokoll weiter.
* Das Erzeugen eines `Client` wählt den Transport. `async with` öffnet ihn.

Sobald der Transport offen ist, müssen sich beide Seiten auf eine Protokollversion einigen. Normalerweise denkst du nie darüber nach; wenn doch, ist **[Protokollversionen](../protocol-versions.md)** die richtige Seite.
