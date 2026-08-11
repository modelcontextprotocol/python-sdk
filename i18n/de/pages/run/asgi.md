---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# In eine bestehende App einbinden {#add-to-an-existing-app}

`mcp.run("streamable-http")` startet einen Webserver für dich. Manchmal willst du das nicht: Dein MCP-Server ist ein Teil einer größeren Webanwendung, oder du hast bereits ein ASGI-Deployment.

Dafür gibt `mcp.streamable_http_app()` eine **Starlette-Anwendung** zurück.

Eine Starlette-App ist eine ASGI-App. Alles, was ASGI hosten kann (uvicorn, Hypercorn, ein anderes Starlette, FastAPI), kann also auch deinen MCP-Server hosten.

## Die App {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` ist eine ganz normale ASGI-Anwendung. Übergib sie einem beliebigen ASGI-Server:

```console
uvicorn server:app
```

Der MCP-Endpunkt liegt unter `/mcp`, ein Client verbindet sich also mit `http://127.0.0.1:8000/mcp`.

Die App bringt bereits zwei Dinge mit:

* Eine Route, `/mcp`: den Streamable-HTTP-Endpunkt.
* Einen **Lifespan** (Start- und Stopp-Phase des Servers), der `mcp.session_manager` startet – das Objekt, dem die Hintergrundarbeit jeder aktiven Session gehört.

Betreibst du die App für sich allein (`uvicorn server:app`), musst du über keines von beiden nachdenken.

!!! tip
    `streamable_http_app()` nimmt dieselben Keyword-Argumente wie `mcp.run("streamable-http", ...)`,
    abzüglich `port`: Der Port gehört dem, was die App ausliefert. `host` wird weiterhin akzeptiert,
    bindet hier aber nichts; **[Bereitstellen und skalieren](deploy.md)** erklärt, was es tatsächlich steuert.
    **[Den Server betreiben](index.md)** behandelt die Optionen selbst.

`mcp.sse_app()` macht dasselbe für den abgelösten SSE-Transport.

## Nur localhost, bis du etwas anderes sagst {#localhost-only-until-you-say-otherwise}

Ohne weitere Konfiguration beantwortet die App **nur** Requests an localhost. `streamable_http_app()`
kann nicht wissen, hinter welchem Hostnamen sie ausgeliefert wird, also aktiviert sie den Schutz vor DNS-Rebinding mit der
sichersten möglichen Allowlist; auf deinem Rechner ist das genau richtig. Hinter einem echten Hostnamen bereitgestellt
heißt das: **Jeder Request wird mit `421 Misdirected Request` abgelehnt**, bis du
`transport_security=` eine Allowlist dessen übergibst, was du tatsächlich auslieferst. Nichts von dem, was du gebaut hast, wird
vorher überhaupt gefragt. Diese Allowlist – und alles andere zwischen einer funktionierenden App und einem echten Hostnamen –
steht in **[Bereitstellen und skalieren](deploy.md)**.

## Die App mounten {#mounting-it}

Sobald der MCP-Server *Teil* einer größeren Anwendung ist, steckst du die App in einen `Mount`. Und sobald du das tust, wird der Lifespan zu deinem Problem:

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` plus der Standardpfad `/mcp` lässt den Endpunkt unter `/mcp`. Starlette probiert die Routen der Reihe nach durch, und `Mount("/")` passt auf **jeden** Pfad, deshalb stehen deine eigenen Routen in der Liste *davor*. Alles dahinter ist unerreichbar.
* Die Funktion `lifespan` betritt `mcp.session_manager.run()` für die Lebensdauer der **Host**-App. Das ist die Zeile, die alle vergessen.
* `mcp.session_manager` existiert erst, *nachdem* `streamable_http_app()` aufgerufen wurde. Deshalb werden die Routen auf Modulebene gebaut und der Manager wird erst im Lifespan angefasst.

Starlettes `Host`-Route funktioniert genauso: Ersetze `Mount("/", ...)` durch `Host("mcp.example.com", ...)`, um nach Hostname statt nach Pfad zu routen. Die Lifespan-Regel ändert sich nicht, und die zur Transport-Security auch nicht. Eine `Host("mcp.example.com", ...)`-Route empfängt nur Requests an genau diesen Hostnamen, aber die eigene Host-Allowlist des Transports (**[Bereitstellen und skalieren](deploy.md)**) läuft trotzdem zuerst. Ohne `"mcp.example.com"` darin beantwortet diese Route jeden einzelnen davon mit einem `421`.

!!! warning "Der Lifespan gehört der Host-App"
    `streamable_http_app()` hängt `session_manager.run()` in den Lifespan des Starlette ein, das es
    zurückgibt, aber **der Lifespan einer gemounteten Unteranwendung läuft nie**. Mounte die App, und dieser
    eingebaute Lifespan ist toter Code. Welche App auch immer ganz oben in deinem ASGI-Stack sitzt, muss
    `mcp.session_manager.run()` in ihrem eigenen Lifespan betreten.

!!! check
    Lösche die Zeile `lifespan=lifespan` und starte den Server. Er startet. Die Route wird aufgelöst.
    Dann schlägt der erste Request an `/mcp` fehl mit:

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    Nichts startet den Session-Manager außer seinem `run()`.

## Zwei Server, eine App {#two-servers-one-app}

Jeder `MCPServer` ist eine eigene App mit eigenem Session-Manager. Mounte so viele, wie du willst; betritt jeden Manager aus dem einen Host-Lifespan heraus:

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` betritt beide Manager; sie starten gemeinsam und fahren in umgekehrter Reihenfolge herunter.
* Die Endpunkte sind `/notes/mcp` und `/tasks/mcp`: das Mount-Präfix plus der Standardpfad.

## Den Pfad ändern {#changing-the-path}

Das abschließende `/mcp` ist `streamable_http_path`. Setze es auf `"/"`, und das Mount-Präfix wird zum gesamten öffentlichen Pfad:

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

Jetzt verbinden sich Clients mit `/notes`, nicht mit `/notes/mcp`.

## CORS für Browser-Clients {#cors-for-browser-clients}

Ein browserbasierter Client braucht zwei Erlaubnisse von dir: seine MCP-Request-Header zu **senden** und den einen zu **lesen**, den MCP zurückschickt. Beides ist CORS-Konfiguration in der Host-App, und die Transport-Security-Allowlist von oben muss damit übereinstimmen:

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` ist die Hälfte, die alle vergessen. Ein Browser schickt für jeden MCP-Request einen **Preflight**, weil `Content-Type: application/json` und die `Mcp-*`-Request-Header nicht auf der CORS-Safelist stehen, und ein Header, den der Preflight nicht gewährt, ist ein Request, den der Browser nie sendet. (`allow_headers=["*"]` funktioniert auch: Starlette beantwortet einen Preflight mit allem, wonach er gefragt hat.)
* `expose_headers=["Mcp-Session-Id"]` ist die Lese-Hälfte. Streamable HTTP gibt die Session-ID in diesem Response-Header zurück, und Browser verbergen Response-Header vor JavaScript, solange CORS sie nicht namentlich freigibt. Ohne das kann der Client seinen zweiten Request nie stellen.
* `allow_origins` ist deine Entscheidung, nicht die von MCP. Sei präzise und spiegle es oben in `allowed_origins=`: Der Browser setzt CORS durch, aber der Server prüft `Origin` selbst, und ein Origin, dem der Transport nicht vertraut, bekommt auch nach einem sauberen Preflight ein `403`.
* `allow_methods` listet die drei Methoden auf, die Streamable HTTP verwendet: `POST` zum Senden von Nachrichten, `GET` zum Öffnen des Streams vom Server zum Client, `DELETE` zum Beenden der Session.

## Eigene Routen {#custom-routes}

`@mcp.custom_route()` registriert einen einfachen HTTP-Endpunkt auf derselben App – für die Dinge, die jeder bereitgestellte Dienst braucht und die nichts mit MCP zu tun haben: einen Health-Check, einen OAuth-Callback.

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* Der Handler ist reines Starlette: eine `async`-Funktion von `Request` nach `Response`.
* `streamable_http_app()` sammelt jede eigene Route ein. `app.routes` ist jetzt `/mcp` und `/health`.
* `GET /health` antwortet mit `{"status": "ok"}`, weit und breit kein MCP.

!!! warning
    Eigene Routen sind **nie authentifiziert**, selbst wenn der Rest des Servers es ist. Das ist
    Absicht: Health-Checks und OAuth-Callbacks müssen erreichbar sein, bevor irgendein Token existiert.
    Lege nichts Vertrauliches dahinter.

## Zusammenfassung {#recap}

* `mcp.streamable_http_app()` gibt eine Starlette-App mit einer Route zurück, `/mcp`. Jeder ASGI-Server kann sie betreiben.
* Ohne weitere Konfiguration beantwortet die App nur Requests an localhost, und hinter einem echten Hostnamen lehnt sie alles mit einem `421` ab, bis du `transport_security=` eine Allowlist übergibst. Das gehört zu **[Bereitstellen und skalieren](deploy.md)**, ebenso wie der Rest des Wegs in die Produktion.
* `Mount` (oder `Host`) steckt sie in eine größere Starlette- oder FastAPI-App.
* **Mounten deaktiviert den eingebauten Lifespan.** Der Lifespan der Host-App muss `mcp.session_manager.run()` betreten, sonst schlägt der erste Request fehl.
* Mehrere Server in einer App heißt mehrere Mounts und ein Lifespan, der jeden Session-Manager betritt.
* `streamable_http_path="/"` verschiebt den Endpunkt auf das Mount-Präfix selbst.
* Browser-Clients brauchen CORS: `allow_headers` für die `Mcp-*`-Request-Header, `expose_headers=["Mcp-Session-Id"]` für die Response.
* `@mcp.custom_route()` fügt einfache, nicht authentifizierte HTTP-Endpunkte neben `/mcp` hinzu.

Sobald der Server unter einer echten URL erreichbar ist, verbindet sich **[Der Client](../client/index.md)** über diese URL mit ihm statt über ein Server-Objekt.
