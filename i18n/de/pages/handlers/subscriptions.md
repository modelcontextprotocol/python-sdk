---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# Abonnements {#subscriptions}

Der Katalog eines Servers ist nicht fest. Tools tauchen zur Laufzeit auf, und der Inhalt hinter einem Ressourcen-URI ändert sich.

Über **Abonnements** erfährt ein Client davon. Der Client sendet einen einzigen `subscriptions/listen`-Request, und die Response auf diesen Request *ist* der Stream: Er bleibt offen und trägt die Änderungsbenachrichtigungen, die der Client angefordert hat.

## Aus dem Tool heraus veröffentlichen {#publish-it-from-the-tool}

Dein Anteil daran ist eine Zeile: Veröffentliche die Änderung.

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` erreicht jeden offenen Stream, der diesen URI abonniert hat. Sonst niemanden.
* `await ctx.notify_tools_changed()` erreicht jeden Stream, der Änderungen an der Tool-Liste angefordert hat. Ein Client, der das empfängt, ruft `tools/list` erneut auf und sieht jetzt `sprint_report`.
* Die Geschwister heißen `notify_prompts_changed()` und `notify_resources_changed()`.
* Keine Abonnenten, keine Arbeit. Auf einem untätigen Server zu veröffentlichen ist ein No-op, deshalb prüfst du nie, ob jemand zuhört. Du gibst an, was sich geändert hat.

`MCPServer` bedient `subscriptions/listen` für dich. Die Pflichten auf der Leitung (die Bestätigung als erster Frame, das Filtern pro Stream, die Abonnement-ID auf jedem Frame) sind Sache des SDK.

!!! check
    Auf der Leitung sieht ein Stream, dessen Filter `board://sprint` nannte, so aus, nachdem `complete_task` gelaufen ist:

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    Beachte, was das Update *nicht* trägt: das Board. Jeder Frame trägt die JSON-RPC-ID des listen-Requests unter `_meta`, und diese ID ist die Abonnement-ID. Der Client vergibt sie: Der Python-`Client` verwendet Strings wie `"listen-1"`; andere Clients verwenden vielleicht Ganzzahlen.

## Nur das, was angefordert wurde {#only-what-was-asked-for}

Der Filter ist ein Vertrag. Ein Stream, der Änderungen an der Tool-Liste und einen Ressourcen-URI angefordert hat, empfängt diese beiden Arten und nichts anderes. Veröffentlichst du eine Prompt-Änderung, bleibt dieser Stream still.

`MCPServer` vergleicht Ressourcen-URIs als exakte Strings, deshalb hört ein Stream, der `board://sprint` nannte, nichts über `board://sprint/tasks/1`. Die Spezifikation erlaubt einem Server, eine Änderung an einer Unterressource eines abonnierten URI zu melden; `MCPServer` tut das nie, aber Clients sind darauf ausgelegt, damit zu rechnen.

Zwei Dinge, die der Stream *nicht* ist:

* **Er ist kein Wiederholungsprotokoll.** Ein abgebrochener Stream ist weg, und Ereignisse, die veröffentlicht wurden, während niemand verbunden war, werden nicht zwischengespeichert. Clients horchen erneut und laden neu.
* **Er ist nicht der Pfad von 2025.** Clients, die `resources/subscribe` aufgerufen haben, werden über `ctx.session.send_resource_updated(uri)` bedient. Die `notify_*`-Methoden erreichen nur `subscriptions/listen`-Streams.

## Entscheiden, wer zusehen darf {#deciding-who-may-watch}

Standardmäßig wird jede angeforderte Art und jeder URI akzeptiert: Jeder Aufrufer darf jeden URI beobachten, den du veröffentlichst. Nichts befragt deinen Lese-Handler, weil niemand liest – ein Aufrufer, den dein `files://{name}`-Handler abweisen würde, kann trotzdem einen Stream auf `files://payroll.csv` öffnen und erfahren, dass und wann sich die Datei geändert hat. Er erfährt nie Inhalte, und er kann nicht ertasten, was existiert, denn ein unbekannter URI wird ebenfalls akzeptiert und feuert schlicht nie. Schmal, aber real – sichere es also ab, bevor du personenbezogene URIs von einem mandantenfähigen Server veröffentlichst.

Die Absicherung ist eine Middleware. Sie sieht den `subscriptions/listen`-Request, bevor das SDK ihn bestätigt, und lehnt ab, wenn der Aufrufer etwas anfordert, das er nicht lesen darf:

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` ist der rohe Request, deshalb validiert die Middleware ihn selbst zu `SubscriptionsListenRequestParams` und liest den Filter, den der Client angefordert hat.
* Eine Ablehnung ist ein ausgelöster `MCPError` vor `call_next(ctx)`: Der Client bekommt diesen Fehler und keinen Stream, und die Verbindung läuft weiter. Halte die Meldung einheitlich und nenne keinen URI, damit eine Ablehnung nie bestätigt, welche URIs geschützt sind.
* Ein einziges `can_access(user, uri)` beantwortet beide Fragen. Der Ressourcen-Handler fragt es bei `resources/read`; die Middleware fragt es bei `subscriptions/listen`. Tausche die Tabelle gegen eine Datenbank oder dein RBAC-System aus, und beide bleiben im Gleichschritt.
* Die Entscheidung gilt für die Lebensdauer des Streams. Es gibt keine erneute Prüfung pro Ereignis. Kann der Zugriff eines Aufrufers also mitten im Stream erlöschen (ein ablaufendes Token), beende die Verbindung dieses Aufrufers, sobald das geschieht.

Der vollständige Middleware-Vertrag, einschließlich dessen, was sie sonst noch umschließt und warum sie als vorläufig markiert ist, steht auf **[Middleware](../advanced/middleware.md)**.

## Die Client-Seite {#the-client-end}

Hier ist ein Client auf der anderen Seite dieses Streams, der dem Board folgt:

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Beim Betreten von `client.listen(...)` wird der Request gesendet und auf deine Bestätigung gewartet, sodass der Stream aktiv ist, wenn der Block beginnt, und jedes typisierte Ereignis ist ein Signal zum Neuladen, nie eine Payload. Das ist der ganze Vertrag auf einem Bildschirm. Alles andere zur Client-Seite steht auf einer eigenen Seite: neben einem Hauptablauf beobachten, Stream-Enden und erneutes Horchen. Siehe **[Abonnements](../client/subscriptions.md)** unter *Clients*.

## Über einen Prozess hinaus skalieren {#scaling-past-one-process}

Veröffentlichungen wandern von deinem Handler über einen `SubscriptionBus` zu den offenen Streams. Der Standard arbeitet im Speicher: ein Prozess, jeder Stream darin. Das ist die richtige Antwort, bis du Replikate hinter einem Load Balancer betreibst, denn dann ist der Stream eines Clients an ein Replikat gebunden, und eine Veröffentlichung auf einem anderen Replikat muss ihn erreichen.

Diese Nahtstelle implementierst du selbst: zwei Methoden über deinem Pub/Sub-Backend.

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` gehört dir, ebenso der Lese-Task auf jedem Replikat, der eintreffende Nachrichten dekodiert und jeden registrierten Listener aufruft. Listener sind synchron, dürfen keine Exception auslösen und laufen auf der Event-Loop des Servers.

Der Bus trägt typisierte `ServerEvent`-Werte, vier kleine Dataclasses, nie JSON-RPC. Stempeln, Filtern und Stream-Lebenszyklen bleiben im SDK, sodass eine Bus-Implementierung das Protokoll nicht brechen kann. Sie kann nur Ereignisse zwischen Prozessen bewegen.

Um außerhalb eines Requests zu veröffentlichen, erzeuge den Bus selbst, damit du die Referenz hältst. `MCPServer` baut intern einen, wenn du nichts übergibst, und legt ihn nicht offen.

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## Die Low-Level-Komposition {#the-low-level-composition}

Unten auf dem Low-Level-`Server` ist nichts vorverdrahtet, und dieselben Teile setzen sich in drei Zeilen zusammen:

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* Der Bus gehört dir, also veröffentlichst du direkt darauf: `await bus.publish(ResourceUpdated(uri=...))`. Lege ihn dorthin, wo deine Handler ihn erreichen: hier auf Modulebene, in einer größeren App im Lifespan.
* `ListenHandler(bus)` ist derselbe Handler, den `MCPServer` registriert, und `on_subscriptions_listen=` ist ein gewöhnlicher Handler-Slot. Setze dein eigenes Callable in diesen Slot für eine andere Semantik, und die Pflichten aus der Spezifikation gehen auf dich über: zuerst bestätigen, jeden Frame mit der Abonnement-ID stempeln, nichts außerhalb des Filters ausliefern.
* `ListenHandler.close()` beendet jeden offenen Stream geordnet. Jeder empfängt das Ergebnis des listen-Requests als letzten Frame – so sagt die Spezifikation, dass der Server das Abonnement absichtlich beendet hat. Die Methode kehrt zurück, bevor diese Streams fertig geleert sind, gib ihnen also einen Moment, bevor du den Transport abbaust. Ohne sie enden Streams, wenn der Client die Verbindung trennt.

## Zusammenfassung {#recap}

* Ein Client steigt mit einem einzigen `subscriptions/listen`-Request ein, und die Response ist der Stream. Ihn zu bedienen ist eingebaut.
* Du veröffentlichst mit `ctx.notify_*`, und das SDK übernimmt Stempeln, Filtern und die Lebenszyklus-Arbeit.
* Ereignisse sind Signale, keine Payloads. Beide Seiten laden neu.
* Die Client-Seite ist `async with client.listen(...)`: Alles Weitere steht in **[Abonnements](../client/subscriptions.md)** unter *Clients*.
* Auf dem Low-Level-`Server` setzt du dieselben Teile selbst zusammen: einen Bus, `ListenHandler(bus)`, den Slot `on_subscriptions_listen`.
* Horizontal skalieren heißt, `SubscriptionBus` zu implementieren, zwei Methoden, und ihn als `MCPServer(subscriptions=...)` zu übergeben.

Den Server zu betreiben, der all das bedient, hinter einem Replikat oder zwanzig, ist **[Bereitstellen und skalieren](../run/deploy.md)**.
