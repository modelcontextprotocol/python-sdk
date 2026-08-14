---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# Client-Transporte {#client-transports}

Jeder `Client` spricht mit seinem Server über einen **Transport**: das, was die Nachrichten tatsächlich befördert.

Du konfigurierst nie einen separat. `Client` nimmt ein einziges positionales Argument und leitet den Transport aus dessen Typ ab.

Die *Server*-Seite jedes Transports (was `mcp.run()` tut und was du bereitstellst) steht in **[Den Server betreiben](../run/index.md)**.

## Im Speicher {#in-memory}

Übergib das Server-Objekt selbst:

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

Kein Subprozess, kein Port, keine Bytes auf einer Leitung. Client und Server sind zwei Objekte im selben Prozess, und der Aufruf läuft trotzdem durch die echte Protokollschicht: `search_books` wird genau so aufgelistet, validiert und aufgerufen, wie es über HTTP geschähe.

Damit ist es zwei Dinge zugleich:

* **Eine Testumgebung.** Jedes Beispiel in dieser Dokumentation wird so ausgeführt, und die Seite **[Testen](../get-started/testing.md)** baut das ganze Muster darauf auf.
* **Eine Embedding-API.** Eine Anwendung, die den Server selbst erzeugt, braucht keinen Netzwerk-Hop, um dessen Tools aufzurufen.

## Streamable HTTP {#streamable-http}

Übergib einen URL-String und du bekommst **Streamable HTTP**, den Transport, hinter dem du bereitstellst:

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

Das ist der ganze Produktions-Client. `Client` packt die URL für dich in `streamable_http_client(...)`, auf Basis eines `httpx2.AsyncClient`, der so konfiguriert ist, wie MCP es braucht: `follow_redirects=True`, ein Timeout von 30 Sekunden für connect/write/pool und ein Read-Timeout von 300 Sekunden, weil der Server einen Response-Stream offen halten kann.

!!! check
    Ein `Client`, den du erzeugt hast, ist **nicht** verbunden. Das Erzeugen wählt nur den Transport;
    erst `async with` öffnet ihn. Greifst du vor dem Eintreten auf die Verbindung zu, sagt dir das SDK das:

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    Nichts wurde aufgelöst, abgerufen oder gestartet, als du `Client("http://...")` geschrieben hast. Diese Zeile kostet nichts.

### Einen eigenen `httpx2.AsyncClient` mitbringen {#bring-your-own-httpx2asyncclient}

Sobald du einen `Authorization`-Header, ein Cookie, einen Proxy, mTLS oder ein anderes Timeout brauchst, baust du den `httpx2.AsyncClient` selbst und übergibst ihn an `streamable_http_client`:

```python title="client.py" hl_lines="8-14"
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
    nichts weg. Hier dockt auch OAuth an:
    `httpx2.AsyncClient(auth=OAuthClientProvider(...))`. Der ganze Ablauf steht in **[OAuth-Clients](oauth-clients.md)**.

## stdio {#stdio}

Ein **stdio**-Server ist ein Subprozess. Der Client startet ihn, schreibt JSON-RPC in seine stdin und liest JSON-RPC aus seiner stdout. So betreibt ein Desktop-Host einen Server auf deinem Rechner: Ein Host *ist* dieser Code plus eine UI, und **[Mit einem echten Host verbinden](../get-started/real-host.md)** zeigt dieselbe Beziehung von der Seite des Hosts, als Konfigurationsdatei.

Beschreibe den Prozess mit `StdioServerParameters`, mach daraus mit `stdio_client` einen Transport und übergib *den* an `Client`:

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` akzeptiert das Parameter-Objekt allein nicht. `StdioServerParameters` ist Konfiguration; `stdio_client(server)` ist der Transport, der weiß, wie er daraus einen Prozess startet. Immer einpacken.

Beim Verlassen des `async with`-Blocks wird auch der Subprozess beendet: stdin schließen, warten, abschießen, falls er hängen bleibt. Du räumst ihn nie selbst auf.

!!! warning
    Der Kindprozess erbt **nicht** deine Umgebung. Er bekommt eine minimale Allow-List (`HOME`, `LOGNAME`,
    `PATH`, `SHELL`, `TERM` und `USER` auf POSIX), damit nichts Sensibles in einen Prozess durchsickert, den du
    vielleicht nicht selbst geschrieben hast.

    Ein Server, der einen API-Key braucht, findet ihn dort nicht. Übergib ihn explizit mit `env=`; diese
    Variablen werden über die Allow-List gelegt. Genau das tut `BOOKSHOP_API_KEY` oben.

## SSE {#sse}

`sse_client(url)` aus `mcp.client.sse` ist der HTTP-Transport, den Streamable HTTP abgelöst hat. Pack ihn genauso ein, `Client(sse_client("http://localhost:8000/sse"))`, um mit einem Server zu sprechen, der ihn noch verwendet – und bau nichts Neues darauf.

## Das `Transport`-Protokoll {#the-transport-protocol}

Für `Client` ist alles oben Genannte dasselbe.

Ein **Transport** ist ein beliebiger asynchroner Kontextmanager, der ein `(read, write)`-Paar von Nachrichten-Streams liefert: formal das `Transport`-Protokoll in `mcp.client`. `Client` löst sein Argument nach Typ auf: Ein Server-Objekt verbindet im Prozess, ein `str` wird zu `streamable_http_client(url)`, und alles andere wird direkt als Transport betreten. Diese letzte Regel ist der Grund, warum `stdio_client(...)`, `streamable_http_client(...)` und `sse_client(...)` alle in denselben Platz passen – und warum du deinen eigenen schreiben kannst.

## Zusammenfassung {#recap}

* `Client(mcp)` (das Server-Objekt) verbindet im Speicher. Nutze es für Tests und zum Einbetten.
* `Client("http://.../mcp")` (eine URL) verbindet über Streamable HTTP, den Produktions-Transport.
* Header, Auth, Proxys und Timeouts gehören auf einen `httpx2.AsyncClient`, den du an `streamable_http_client(url, http_client=...)` übergibst. Es gibt kein Keyword `headers=`.
* stdio ist `Client(stdio_client(StdioServerParameters(...)))`, nie das Parameter-Objekt allein.
* Der Subprozess bekommt eine Umgebung per Allow-List, nicht deine; `env=` ergänzt sie.
* Ein Transport ist alles, womit du `async with x as (read, write)` schreiben kannst. Alles, was weder Server-Objekt noch URL ist, reicht `Client` direkt an dieses Protokoll weiter.
* Das Erzeugen eines `Client` wählt den Transport. `async with` öffnet ihn.

Sobald der Transport offen ist, müssen sich beide Seiten auf eine Protokollversion einigen. Normalerweise denkst du nie darüber nach; wenn doch, ist **[Protokollversionen](../protocol-versions.md)** die richtige Seite.
