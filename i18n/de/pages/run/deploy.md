---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# Bereitstellen und skalieren {#deploy-scale}

Dein Server läuft. Jetzt braucht er einen echten Hostnamen und mehr als einen Worker dahinter.

Fast nichts davon ist Sache von MCP. Du bringst den ASGI-Server, den Prozessmanager und den Load Balancer mit. Diese Seite enthält die kurze Liste der Dinge, die tatsächlich Sache von MCP *sind*: eine Einstellung, an der jedes Deployment hängt, und die zwei Stellen, an denen „mehr als ein Worker“ ändert, was das SDK tut.

## Vor allem anderen: die Host-Allowlist {#before-anything-else-the-host-allowlist}

`streamable_http_app()` kann nicht wissen, hinter welchem Hostnamen es einmal ausgeliefert wird, und nimmt deshalb die sicherste Antwort an: localhost. Ohne `transport_security=` schaltet die App den **DNS-Rebinding-Schutz** ein und akzeptiert einen Request nur, wenn sein `Host`-Header `127.0.0.1:<port>`, `localhost:<port>` oder `[::1]:<port>` lautet. Der `Origin`-Header muss, wenn es einen gibt, die `http://`-Form desselben sein. Auf deinem Rechner ist das genau richtig: Es verhindert, dass eine bösartige Webseite deinen lokalen Server über einen DNS-Namen steuert, den sie auf `127.0.0.1` umgebogen hat.

Hinter einem echten Hostnamen bereitgestellt, weist genau dieser Standard **jeden Request** ab, bis du etwas anderes festlegst. Die Prüfung läuft, bevor irgendetwas MCP-Förmiges an die Reihe kommt – nichts von dem, was du gebaut hast, wird überhaupt gefragt:

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

`transport_security=` ist die Lösung. Setze auf die Allowlist, was du tatsächlich auslieferst:

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* Einträge in `allowed_hosts` sind exakte Strings: `"mcp.example.com"` passt auf einen `Host`-Header ohne Port und `"mcp.example.com:*"` auf jeden Port. Führe beide auf.
* `allowed_origins` spielt nur für Browser eine Rolle, weil sonst nichts `Origin` sendet. Es ist das serverseitige Gegenstück zur CORS-Konfiguration in **[In eine bestehende App einbinden](asgi.md)**.
* Hinter einem Reverse Proxy, der den `Host`-Header ohnehin kontrolliert, ist es die ehrliche Konfiguration, die Prüfung abzuschalten: `TransportSecuritySettings(enable_dns_rebinding_protection=False)`.
* Ein `host=`, das nicht localhost ist (zum Beispiel `host="mcp.example.com"`), setzt diesen Hostnamen **nicht** auf die Allowlist. Es verhindert nur, dass der localhost-Standard den Schutz scharf schaltet – damit wird jeder Host und jeder Origin akzeptiert. Sag stattdessen mit `transport_security=` ausdrücklich, was du meinst.

!!! check
    Lösche das Argument `transport_security=security` und stelle die App trotzdem bereit. Sie startet, `/mcp`
    wird geroutet, und jeder Request (auch von einem schlichten `curl`) kommt so zurück:

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    Diese Worte findest du auf der Client-Seite nicht. Ein `421` ist eine HTTP-Response im Klartext, kein
    JSON-RPC-Fehler; der MCP-Client löst deshalb einen generischen Transportfehler aus. Der Hostname, der
    ihm nicht gefiel, taucht nur im Log des **Servers** auf, als einzelne Warnung. Ein frisch
    bereitgestellter Server, der jede Verbindung ablehnt, ist bis zum Beweis des Gegenteils eine Host-Allowlist.
    Auch **[Fehlerbehebung](../troubleshooting.md)** fängt hier an.

## Worker – und wer sticky sein muss {#workers-and-who-has-to-be-sticky}

Sobald der Hostname antwortet, stellst du mehr als einen Worker dahinter. Dafür gibt es keinen Schalter im SDK; du skalierst eine Starlette-App wie jede andere ASGI-App, indem du das Objekt an etwas übergibst, das forken kann:

```console
uvicorn server:app --workers 4
```

Vier Prozesse, ein Socket. Und jetzt die Frage, die jedes Deployment beantworten muss: **Muss ein Request bei dem Worker landen, der den vorigen gesehen hat?**

Für einen Client, der das Protokoll **2026-07-28** spricht: nein. Ein moderner Request ist ein einziger, in sich geschlossener POST: kein `initialize`-Handshake davor, keine `Mcp-Session-Id` auf der Response, nichts, *zu dem* ein zweiter Request zurückkommen könnte. Leite ihn an einen beliebigen Worker.

Das ist kein Modus, den du einschaltest. `stateless_http=True` sieht so aus, als wäre es einer, aber der Transport routet nach dem Request-Header `MCP-Protocol-Version`, übergibt einen modernen Request an den modernen Handler und **kehrt zurück**. Die Zeile, die `stateless_http` liest, kommt *nach* diesem Return. Das Flag wird auf dem 2026-07-28-Pfad nicht etwa ignoriert – es wird gar nicht erst erreicht. `stateless_http` ist ein Schalter nur für den **Legacy**-Zweig, und der moderne Pfad ist schon von seiner Konstruktion her ohne Session.

Für einen Legacy-Client mit Spezifikationsversion 2025-11-25 oder älter hängt die Antwort von diesem Flag ab:

| Protokollversion des Clients | Session | Was der Load Balancer tun muss |
| --- | --- | --- |
| **2026-07-28** | Keine. `Mcp-Session-Id` wird nie gesetzt. | Nichts. Jeder Worker bedient jeden Request. |
| **2025-11-25 und älter** (der Standard) | `Mcp-Session-Id`, im Speicher eines einzigen Workers gehalten. | **Sticky Sessions.** Ein Folge-Request, der bei einem anderen Worker landet, bekommt ein `404` *„Session not found“*. |
| **2025-11-25 und älter**, mit `stateless_http=True` | Keine. | Nichts. Der Preis sind der Rückkanal (back-channel) vom Server zum Client – Sampling, Push-Elicitation (Rückfrage bei der Person am Host), `roots/list` – und die Wiederaufnehmbarkeit. |

Sticky Sessions und was der Legacy-Zweig kostet, haben ihre eigene Seite: **[Legacy-Clients unterstützen](legacy-clients.md)**; die beiden Generationen selbst stehen in **[Protokollversionen](../protocol-versions.md)**. Hier zählt die Form der Antwort: *Auf 2026-07-28 bist du schon zustandslos, und es gibt nichts zu konfigurieren.*

Der Rest dieser Seite behandelt die zwei Dinge, die dir Zustandslosigkeit **nicht** abnimmt.

## `requestState` über Worker hinweg {#requeststate-across-workers}

Ein **[Multi-Roundtrip-Tool](../handlers/multi-round-trip.md)** (multi-round-trip tool) braucht etwas, das der Client erst besorgen muss (eine Bestätigung, eine Auswahl, eine Zugangsberechtigung). Deshalb gibt es statt einer Antwort eine Frage zurück und wird beim Retry fertig. Zwischen den beiden Runden hält der Client ein undurchsichtiges `request_state`-Token, das der Server ausgestellt hat. Beim Retry muss der Server dieses Token wieder öffnen.

*Unter welchem Schlüssel versiegelt?* Standardmäßig unter einem, den der Server beim Konstruieren mit `os.urandom(32)` erzeugt hat. Unter `--workers 4` sind das vier Konstruktionen in vier Prozessen: vier verschiedene Schlüssel, nirgends gespeichert, nie geteilt, beim Neustart weg.

Hier ein Tool, das fragt, bevor es handelt, auf einem Server, der nichts konfiguriert:

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

Die erste Runde landet bei Worker A. Worker A versiegelt `refund:120` unter **seinem** Schlüssel und gibt das Token zurück. Der Client legt die Frage einer Person vor, bekommt ein Ja und versucht es erneut. Der Retry ist ein nagelneuer HTTP-Request.

!!! check
    Lass diesen Retry bei Worker B landen. B versucht, ein Token zu entsiegeln, das er nicht ausgestellt hat,
    scheitert und lehnt die ganze Runde ab. `refund` wird nie aufgerufen; der Client bekommt einen JSON-RPC-Fehler:

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    Diese Meldung ist **festgeschrieben**. Abgelaufen, manipuliert, gegen andere Argumente erneut eingespielt oder
    (in einem echten Deployment mit Abstand die häufigste Ursache) von einem Geschwister-Worker versiegelt: Der
    Client bekommt jedes Mal dasselbe gesagt, sodass die Leitung nie verrät, welche Prüfung fehlgeschlagen ist.
    Der wahre Grund ist ein einzelnes `WARNING` im Log des Servers:

    ```text
    requestState rejected on tools/call: unknown key
    ```

    Ein Multi-Roundtrip-Tool, das mit einem Worker funktioniert hat und bei zweien anfing, *manchmal* zu
    scheitern, ist genau das. Beide Runden müssen weiterhin denselben Prozess erreichen, also scheitert es genau
    so oft, wie dein Load Balancer sie trennt.

Die beiden Runden sind zwei unabhängige HTTP-Requests, und mehrere ganz gewöhnliche Dinge trennen sie: ein Proxy, der pro Request verteilt, eine Verbindung, die dazwischen abgebrochen ist, ein Deployment oder ein Neustart, ein Client, der `request_state` gespeichert hat und aus einem ganz anderen Prozess weitermacht (**[Die Schleife selbst steuern](../handlers/multi-round-trip.md#driving-the-loop-yourself)**). Jedes davon ist „ein anderer Worker“.

Die Lösung ist ein einziges Argument. Es hat **zwei** Hälften.

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** ist die Hälfte, die alle finden. Gib jeder Instanz dasselbe Secret (mindestens 32 Bytes davon), und jede Instanz kann entsiegeln, was irgendein Geschwister ausgestellt hat. `keys[0]` versiegelt, und jeder Schlüssel in der Liste entsiegelt – das ist der Rotationsring; **[Schlüssel rotieren](../handlers/multi-round-trip.md#rotating-keys)** zeigt, wie du ihn ohne Downtime drehst.
* **Der Name des Servers** ist die Hälfte, die fast niemand findet, und der Grund, warum instanzübergreifende Retries auch dann noch scheitern, nachdem du den Schlüssel geteilt hast. Jedes versiegelte Token trägt den `name` des Servers als **Audience-Claim**, der auf dem Rückweg strikt geprüft wird. Zwei Instanzen aus demselben Code haben denselben Namen und merken nie etwas davon. Benenne sie unterschiedlich (`MCPServer(f"billing-{POD}")` liest sich wie gute Observability-Hygiene), und jeder instanzübergreifende Retry wird genau wie oben abgelehnt, geteilter Schlüssel hin oder her. Im Log steht `audience` statt `unknown key`; der Client kann den Unterschied nicht erkennen.

Erzeuge das Secret einmal und gib jeder Instanz denselben Wert. Das ist der Befehl, den dir die eigene Fehlermeldung des SDK nennt, wenn du weniger als 32 Bytes übergibst:

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "Dieselben Schlüssel *und* derselbe Name"
    Ein Deployment mit mehreren Instanzen muss beides teilen. Wenn Namen pro Instanz für dich tragend sind,
    gib der ganzen Flotte stattdessen eine explizite Audience: `RequestStateSecurity(keys=[...], audience="billing")`.
    Jede Instanz stellt dann unter `"billing"` aus und akzeptiert darunter, egal wie sie heißt.

Alles Weitere zum Siegel steht in **[`requestState` schützen](../handlers/multi-round-trip.md#protecting-requeststate)**: was es bindet, die `ttl` pro Runde (standardmäßig 600 Sekunden), wie du einen eigenen Codec mitbringst und warum der unkonfigurierte Standard auf `stdio` genau richtig ist. Der ganze Beitrag dieser Seite ist eine Checkliste mit zwei Punkten: *dieselben Schlüssel, derselbe Name.*

!!! info
    Du bist auf diesem Pfad, auch wenn du nie `InputRequiredResult` getippt hast. Ein Tool, dessen Parameter
    `Resolve(...)` verwenden (**[Abhängigkeiten](../handlers/dependencies.md)**), ist ein Multi-Roundtrip-Tool,
    und das SDK stellt sein `request_state` für es aus und versiegelt es. Derselbe Standardschlüssel, derselbe
    Fehler über Worker hinweg, dieselbe Lösung.

## Änderungsbenachrichtigungen über Replikate hinweg {#change-notifications-across-replicas}

Der `subscriptions/listen`-Stream eines Clients ist eine einzige langlebige Response und hängt deshalb sein ganzes Leben lang an einem Replikat. Ein `ctx.notify_resource_updated(...)`, das auf einem **anderen** Replikat veröffentlicht wird, muss ihn erreichen.

Die Nahtstelle zwischen beiden ist der `SubscriptionBus`. Welchen Bus du einem Server auch gibst – in ihn geht jedes Publish, und auf ihm lauscht jeder offene Stream. Gib also jedem Replikat denselben Bus:

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

Dem Fan-out ist es egal, an welchem Server-Objekt ein Stream hängt. Zwei Server, die sich einen `InMemorySubscriptionBus` teilen, verhalten sich schon so: Öffne einen Listen-Stream auf dem einen, rufe `edit_note` auf dem anderen auf, und der Stream erfährt davon. Dieser In-Memory-Bus reicht nur über Server-Objekte innerhalb eines Prozesses, was ihn zum Modell macht, nicht zum Deployment:

* Über echte Prozesse hinweg **liefert das SDK keinen Bus mit, der dir helfen kann.** `SubscriptionBus` ist ein `Protocol` mit zwei Methoden (`publish` und `subscribe`), das du über deinem eigenen Pub/Sub-Backend implementierst (Redis, NATS, was auch immer du schon betreibst) und als `MCPServer(subscriptions=...)` übergibst. Die Skizze und den Vertrag findest du in **[Abonnements](../handlers/subscriptions.md#scaling-past-one-process)**.
* Der Bus transportiert vier kleine typisierte Events, nie JSON-RPC. Bestätigung, Filterung und Stream-Lebenszyklus bleiben im SDK, sodass dein Bus das Protokoll nicht kaputt machen kann; er kann nur Events zwischen Prozessen bewegen.
* Streams sind **nicht** wiederaufnehmbar, und Events werden **nicht** erneut abgespielt. Fällt ein Replikat weg, fallen seine Streams weg; die Clients lauschen erneut und holen die Daten erneut ab. Es gibt keinen Event Store zu teilen und sonst nichts zu konfigurieren. Das ist die eine Stelle, an der horizontales Skalieren wirklich nur mehr vom Gleichen ist.

## Was das SDK dir nicht gibt {#what-the-sdk-does-not-give-you}

Ein `MCPServer` ist eine Protokollimplementierung, kein Anwendungsserver. Die Deployment-Schalter, nach denen du als Nächstes suchst, fehlen absichtlich:

* **Kein `workers=`.** `mcp.run("streamable-http")` startet genau einen uvicorn-Prozess, und mehr wird es nie starten. Mehrere Prozesse heißt: `streamable_http_app()` an das übergeben, womit du ASGI ohnehin bereitstellst – `uvicorn --workers`, gunicorn, der Prozessmanager deiner Plattform. Diese Seite ist absichtlich kein Tutorial für irgendeines davon; deren Dokumentation ist besser, als es eine Kopie davon hier wäre.
* **Keine Health-Check-Route.** `@mcp.custom_route("/health", methods=["GET"])` ist die ganze Antwort, und sie wird nie authentifiziert, selbst wenn der Rest des Servers es ist. Für eine Liveness-Probe ist das richtig, für alles Private falsch. **[In eine bestehende App einbinden](asgi.md#custom-routes)** zeigt eine.
* **Kein Objekt für Produktionseinstellungen.** Auf `MCPServer` gibt es keinen Ort, um Timeouts, TLS, geordnetes Herunterfahren oder Verbindungslimits festzuhalten, weil nichts davon seine Aufgabe ist. Sie gehören zu deinem ASGI-Server, und dort konfigurierst du sie. **[Den Server betreiben](index.md)** behandelt die paar Einstellungen, die der Konstruktor *tatsächlich* entgegennimmt.
* **Kein mitgelieferter `EventStore` – und auf 2026-07-28 auch keine Verwendung dafür.** Wiederaufnehmbarkeit ist ein Feature des zustandsbehafteten Legacy-Zweigs; ein moderner Austausch ist ein POST, eine Response und nichts, was wiederaufzunehmen wäre.

## Zusammenfassung {#recap}

* Ohne weitere Konfiguration beantwortet die App nur Requests an localhost. `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` ist die Schranke zum Livegang: Bis du es übergibst, ist jeder Request hinter einem echten Hostnamen ein `421`, und der Grund steht nur im Log des Servers.
* Auf 2026-07-28 gibt es keine Session und nichts, woran ein Load Balancer sticky sein könnte. `stateless_http=True` ist ein reiner Legacy-Schalter, weil ein moderner Request geroutet und beantwortet ist, bevor dieses Flag überhaupt gelesen wird.
* Der Standardschlüssel für `requestState` ist `os.urandom(32)`, pro Prozess erzeugt. Ein Multi-Roundtrip-Retry, der bei einem anderen Worker landet, scheitert mit `-32602` *„Invalid or expired requestState“*.
* Die Lösung ist `RequestStateSecurity(keys=[...])` **und** derselbe Servername auf jeder Instanz. Der Name ist der Standard-Audience-Claim des Tokens. Dieselben Schlüssel, derselbe Name.
* Änderungsbenachrichtigungen überqueren Replikate über einen gemeinsamen `SubscriptionBus`. Die einzige Implementierung des SDK läuft innerhalb eines Prozesses; das `Protocol` mit zwei Methoden über deinem eigenen Pub/Sub schreibst du selbst.
* Es gibt kein `workers=`, keine Health-Route, kein Objekt für Produktionseinstellungen. Bring deinen eigenen ASGI-Server mit.

Das andere, was ein echter Hostname vor sich braucht, ist ein Token: **[Autorisierung](authorization.md)**.
