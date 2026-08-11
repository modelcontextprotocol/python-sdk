---
translation:
  sections: [3d1663c18edc824c, d4fd37009a13f03d, af9f398a5a8b679a, 470c2dd144294d69, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# Legacy-Clients unterstützen {#serving-legacy-clients}

MCP kennt zwei Protokollgenerationen: die Generation des `initialize`-Handshakes, bis zur Spezifikationsversion `2025-11-25`, und die moderne Generation, `2026-07-28`. **[Protokollversionen](../protocol-versions.md)** ist die Seite über diese Trennung selbst.

Diese Seite behandelt die Serverseite dieser Trennung, und die Antwort passt in einen Satz: **Die `streamable_http_app()`, die du ohnehin bereitstellst, bedient beide.**

Das SDK routet jeden Request anhand seines `MCP-Protocol-Version`-Headers. Ein Request, der `2026-07-28` nennt, geht an den modernen Handler. Ein Request, der eine Version der Handshake-Generation nennt oder gar keinen Header trägt (so kommt das `initialize` eines Clients von vor 2026 an), geht an den Transport, den diese Clients erwarten: `initialize`-Handshake, Sessions und alles, was dazugehört. Das passiert pro Request, vor deinem Code, in der einen App.

Ein Legacy-Client ist also nichts, *wofür* du etwas baust. Er ist etwas, das sich *mit* dem Server verbindet, den du schon geschrieben hast. Du konfigurierst nichts.

!!! note
    Nichts, wortwörtlich. Es gibt keine Option `legacy=`, keine Allowlist für Versionen, keine
    Möglichkeit, eine Generation abzulehnen oder abzuschalten: nicht an `streamable_http_app()`,
    nicht an `run()`, nicht am Session-Manager. Beide Generationen sind immer aktiv. Was in dieser
    Signatur einem Schalter pro Generation am nächsten kommt, ist `stateless_http` – und darum geht
    es auf dem Großteil dieser Seite.

## Ein Handler, beide Generationen {#one-handler-both-eras}

Hier ist ein Tool, das die Person am Host etwas fragen muss, und Clients beider Generationen, die es aufrufen:

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` braucht eine Sache, die das Modell nicht geliefert hat: wie viele Exemplare. Mit `Annotated[..., Resolve(ask_quantity)]` deklariert ein Tool genau das (alles Weitere steht in **[Abhängigkeiten](../handlers/dependencies.md)**). Nichts in `reserve` nennt eine Version, prüft eine Capability oder verzweigt.

Die beiden Clients sind **gleichzeitig** offen, am selben `mcp`-Objekt. `mode="legacy"` führt den `initialize`-Handshake aus: genau die Verbindung, die ein Client von vor 2026 öffnet. Der andere nimmt den Standardwert und landet bei `2026-07-28`.

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

Derselbe Server, derselbe Handler, dieselbe Antwort. Das ist das ganze Feature.

Es lohnt sich, beim *Wie* kurz innezuhalten, denn den beiden Clients wurde dieselbe Frage über zwei völlig verschiedene Leitungen gestellt. Die `2026-07-28`-Verbindung hat keinen Kanal, auf dem der Server einen Request senden könnte, also gab `Resolve` die Frage im Tool-Ergebnis zurück, und der Client wiederholte den Aufruf mit der Antwort (**[Multi-Roundtrip-Requests (multi-round-trip requests)](../handlers/multi-round-trip.md)**). Die `2025-11-25`-Verbindung hat so etwas nicht; dort schickte `Resolve` mitten im Aufruf einen echten `elicitation/create`-Request und wartete. Geschrieben hast du keins von beidem. `Resolve` liest die ausgehandelte Version der Verbindung und wählt; dein Tool-Body sieht so oder so eine `AcceptedElicitation`.

!!! tip
    Genau diese Portabilität über Generationen hinweg ist der Grund, *warum* `Resolve` die API ist,
    auf die du bauen solltest. Sein älterer Verwandter `ctx.elicit()`
    (**[Elicitation](../handlers/elicitation.md)**, die Rückfrage bei der Person am Host) sendet
    immer nur `elicitation/create` und funktioniert deshalb immer nur auf einer Legacy-Verbindung.
    Auf einer `2026-07-28`-Verbindung schlägt der Aufruf fehl. Wenn ein Tool es noch verwendet, ist
    die Lösung die, die du oben siehst, und kein Versionscheck.

## Was eine Legacy-Session dich kostet {#what-a-legacy-session-costs-you}

Das Routing ist kostenlos. Die Session nicht.

Eine `2026-07-28`-Verbindung ist **sessionlos**: Jeder Request steht für sich, und der moderne Handler vergibt nie eine `Mcp-Session-Id`. Eine Legacy-Verbindung ist das Gegenteil. Sobald ein Client von vor 2026 `initialize` sendet, erzeugt das SDK eine `Mcp-Session-Id`, gibt sie in einem Response-Header zurück und hält dahinter einen lebenden Eintrag vor, den die späteren Requests des Clients finden: die ausgehandelte Version, die offenen Streams, einen Hintergrund-Task, der die Session antreibt.

Dieser Eintrag ist ein **einfaches `dict` im Prozess**. Es gibt keinen verteilten Session-Store und keine Möglichkeit, einen anzuschließen.

Auf einem Worker ist das unsichtbar. Auf zweien ist es das ganze Problem: Ein Request, der eine `Mcp-Session-Id` trägt und auf einem Worker landet, der sie nicht erzeugt hat, findet in diesem Dict nichts, und die Antwort ist ein `404` (`Session not found`), nicht das Tool-Ergebnis. Sobald du also mehr als einen Worker betreibst, **brauchen Legacy-Clients Sticky Routing**: Jeder Request einer Session muss den Prozess erreichen, der sie gestartet hat. Moderne Clients brauchen das nie; sie haben keine Session, an die sie gebunden sein müssten. **[Bereitstellen und skalieren](deploy.md)** behandelt Stickiness und alles andere rund um den Betrieb von mehr als einer Instanz.

!!! warning
    `event_store=` sieht wie die Lösung aus und ist es nicht. Es ist **Wiederaufnahme** (das
    Nachliefern verpasster SSE-Events an einen Client, der sich mit *derselben* Session neu
    verbindet), kein Session-Store. Es macht eine Session nie von einem anderen Prozess aus
    erreichbar.

## Die eine Stellschraube: `stateless_http` {#the-one-knob-stateless_http}

Wenn Stickiness ein Preis ist, den du nicht zahlen willst, gibt es genau eine Sache, die du ändern kannst.

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

Das ist der Server vom Anfang der Seite plus ein Schlüsselwort. Mit `stateless_http=True` baut der Legacy-Zweig stattdessen pro Request eine Wegwerf-Session: Es wird keine `Mcp-Session-Id` vergeben und nichts zwischen Requests behalten, also kann jeder Worker jeden Request bedienen und der Load Balancer kann tun, was er will.

Zwei Dinge daran sind wichtiger als das, was es tut.

**Es betrifft nur den Legacy-Zweig.** Requests werden anhand des Versions-Headers geroutet, *bevor* `stateless_http` gelesen wird, also sieht der moderne Pfad es nie. Eine `2026-07-28`-Verbindung ist ohnehin sessionlos und verhält sich unter beiden Werten exakt gleich.

**Es kostet auf diesem Zweig beide Kanäle vom Server zum Client.** Eine Session, die nur einen `POST` lang lebt, hat keinen Stream, über den der Server einen Request schicken könnte, und keinen eigenständigen Stream, über den er Benachrichtigungen schicken könnte. Jeder vom Server initiierte Request löst `NoBackChannelError` aus: `ctx.elicit()`, die ausgemusterten Sampling- und Roots-Aufrufe (**[Veraltete Features](../deprecated.md)**) und, ja, auch `Resolve`, wenn es einem *Legacy*-Client seine Frage stellt. Benachrichtigungen bekommen nicht einmal einen Fehler; sie werden stillschweigend verworfen.

!!! note
    `json_response=True` ist nicht diese Stellschraube, verursacht aber auf *jeder* Legacy-Session
    die Hälfte derselben Kosten: Ein `POST`, der mit einem einzigen JSON-Body beantwortet wird, hat
    keinen Stream für den Request-gebundenen Kanal, also löst ein `ctx.elicit()` mitten im Request
    denselben `NoBackChannelError` aus, und an den Request gebundene Benachrichtigungen werden
    verworfen. Der eigenständige Stream der Session bleibt unberührt: Benachrichtigungen ohne Bezug
    zum Request kommen weiterhin an.

!!! check
    Mach es absichtlich falsch. `reserve` ist genau das Tool, das eben beide Clients bedient hat.
    Stelle es mit `stateless_http=True` bereit, verbinde dieselben zwei Clients über HTTP und rufe
    es von jedem aus auf.

    Der moderne Client bekommt weiterhin `Reserved 2 of 'Dune'.` Der moderne Zweig hat sich nicht
    verändert.

    Der Aufruf des Legacy-Clients kommt nicht als `is_error`-Ergebnis zurück, das das Modell lesen
    könnte. Der ganze Request schlägt fehl, als Protokollfehler auf oberster Ebene:

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` hat dich nicht gerettet. Auf einer `2025-11-25`-Verbindung *muss* es
    `elicitation/create` senden, und der Kanal, den es dafür braucht, ist genau das, was
    `stateless_http=True` hergegeben hat. Code, der über Generationen portabel ist, ist nicht
    automatisch Code, der ohne Rückkanal (back-channel) auskommt.

Es ist also eine echte Abwägung, und es gibt sie nur auf dem Legacy-Zweig: **mit Session und sticky, oder zustandslos und nur in eine Richtung.** Wenn deine Tools nie in den Client zurückrufen, ist `stateless_http=True` kostenlos und du solltest es nehmen. Wenn doch, behalte die Sessions und halte das Routing sticky.

## Wo sich dein Code tatsächlich verzweigt {#where-your-code-actually-forks}

Fast nirgends.

Tools, Ressourcen, Prompts, strukturierte Ausgabe, Fortschritt, Fehler: Keines davon kümmert sich darum, welche Generation aufgerufen hat. Der `initialize`-Handshake, die `Mcp-Session-Id`, der eigenständige Stream, das `DELETE`, das eine Session beendet: All das gehört dem SDK, und ein Handler sieht nichts davon. Interaktive Eingabe ist *die* Stelle, an der sich die Generationen auf der Leitung wirklich unterscheiden, und `Resolve` gibt es, damit das nicht dein Problem ist: Du hast gerade zugesehen, wie ein Tool beide bedient.

Genau eine Sache bleibt übrig, und das sind **Änderungsbenachrichtigungen**, weil die beiden Generationen auf verschiedenen Kanälen lauschen:

* Ein `2026-07-28`-Client öffnet einen `subscriptions/listen`-Stream und liest den Abonnement-Bus. `ctx.notify_resource_updated()` (sowie `notify_tools_changed()`, `notify_prompts_changed()`, `notify_resources_changed()`) veröffentlichen dort, und *nur* dort. Alles Weitere steht in **[Abonnements](../handlers/subscriptions.md)**.
* Ein Legacy-Client liest den eigenständigen Stream, den seine Session offen hält. `ctx.session.send_resource_updated()` (sowie `send_tool_list_changed()` und Verwandte) schreiben auf die *Verbindung*, die den Request getragen hat: Bei einer Legacy-Session ist das ihr eigenständiger Stream. Eine moderne Verbindung hat dafür keinen Platz: Über HTTP gibt es keinen solchen Kanal, und über stdio laufen die vier Arten von Änderungsbenachrichtigungen ausschließlich über `subscriptions/listen`-Streams, also wird die Benachrichtigung auf einer modernen Verbindung stillschweigend verworfen.

Über HTTP erreicht keiner der beiden Aufrufe die Clients der jeweils anderen Generation. Um alle zu informieren, rufe beide auf:

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

Zwei Zeilen, kein `if`, kein Versionscheck, und du bist fertig. Das ist die vollständige Liste der Dinge, die ein Handler anders macht, weil es Legacy-Clients gibt.

## Zusammenfassung {#recap}

* Eine `streamable_http_app()` bedient beide Protokollgenerationen. Das SDK routet jeden Request anhand seines `MCP-Protocol-Version`-Headers; es gibt nichts zu konfigurieren und keine Stellschraube pro Generation, nach der du suchen müsstest.
* Ein Legacy-Client kostet dich eine Session: einen `Mcp-Session-Id`-Eintrag im Prozess ohne verteilten Store dahinter. Mehr als ein Worker bedeutet **Sticky Routing**, sonst antwortet der falsche Worker mit `404 Session not found`. Alles zum Betrieb mit mehreren Workern steht in **[Bereitstellen und skalieren](deploy.md)**.
* `stateless_http=True` ist die eine Stellschraube, und sie wirkt **nur auf den Legacy-Zweig**. Sie erkauft freies Load Balancing für Legacy-Clients um den Preis beider Kanäle vom Server zum Client auf diesem Zweig: Vom Server initiierte Requests lösen `NoBackChannelError` aus (beim Client ein Fehler auf oberster Ebene, kein `is_error`-Ergebnis), und Benachrichtigungen werden verworfen.
* Eine `2026-07-28`-Verbindung ist so oder so sessionlos. `stateless_http` berührt sie nie.
* Dein Handler-Code verzweigt nach Generation an genau einer Stelle: Änderungsbenachrichtigungen. `ctx.notify_*` erreicht `subscriptions/listen`-Clients; `ctx.session.send_*` erreicht Legacy-Sessions. Rufe beide auf.
* Alles andere (einschließlich der Rückfrage bei der Person am Host über `Resolve`) ist schon per Konstruktion über Generationen portabel. Schreib die moderne Variante einmal.
