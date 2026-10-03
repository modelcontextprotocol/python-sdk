---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# Abonnements {#subscriptions}

Der Katalog eines Servers steht nicht fest. Tools tauchen zur Laufzeit auf, und der Inhalt hinter einem Ressourcen-URI ändert sich. Ein Client erfährt davon über `client.listen(...)`: ein einziger `subscriptions/listen`-Request, dessen Response der Stream *ist*. Er bleibt offen und trägt die Änderungsbenachrichtigungen, die der Client angefordert hat.

Diese Seite beschreibt das Client-Ende: den Stream öffnen, ihn neben dem Hauptablauf beobachten und mit seinem Ende umgehen. Änderungen veröffentlichen, filtern und die Methode bedienen sind die Server-Seite der Geschichte, erzählt in **[Abonnements](../handlers/subscriptions.md)** unter *Im Handler*. Die Beispiele hier sprechen mit dem dort gebauten Sprint-Board-Server.

## Den Stream beobachten {#watching-the-stream}

Ein Abonnement ist ein einziger Kontextmanager. Beim Betreten wird der Request gesendet – mit deinen Keyword-Argumenten als Abonnementfilter – und auf die Bestätigung des Servers gewartet, sodass der Stream bereits live ist, wenn der Block beginnt.

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

Die Iteration liefert vier typisierte Events: `ToolsListChanged`, `PromptsListChanged`, `ResourcesListChanged` und `ResourceUpdated(uri=...)`.

Ein Event sagt, *was* sich geändert hat, nie *wie*. Deshalb ruft `follow_board` `read_resource` und `list_tools` auf: Das Event ist das Stichwort zum erneuten Abrufen. Lies `event.uri`, statt anzunehmen, welche Ressource sich bewegt hat: Ein Filter kann mehrere URIs nennen, und ein Server kann eine Änderung an einer Unterressource einer davon melden.

Doppelte Events, die auf ihre Verarbeitung warten, fallen zu einem zusammen, und das erneute Abrufen liefert dir trotzdem den aktuellen Stand. Nur identische Events fallen zusammen: Zwei `ResourceUpdated` für verschiedene URIs sind zwei Events.

Zwei weitere Eigenschaften des Handles:

* `sub.honored` ist der Filter, den der Server bestätigt hat: ein `SubscriptionFilter` mit den Feldern, die du übergeben hast, lesbar als Attribute (`sub.honored.prompts_list_changed`). `MCPServer` erfüllt jede Art, die du anforderst, und gibt deinen Request daher unverändert zurück. Ein Server, der weniger Arten unterstützt, bestätigt weniger, und eine bestätigte Art kann trotzdem nie ausgelöst werden. Ein Server kann auch den ganzen Request ablehnen, statt ihn zu bestätigen (siehe [Entscheiden, wer beobachten darf](../handlers/subscriptions.md#deciding-who-may-watch) auf der Server-Seite), was als Fehler des Requests ankommt.
* `sub.subscription_id` ist die ID des listen-Requests, die auf jeden Frame dieses Streams gestempelt ist. Mehrere Abonnements können gleichzeitig offen sein, jedes anhand seiner eigenen ID demultiplext.

## Beobachten, ohne zu blockieren {#watching-without-blocking}

`follow_board` läuft, bis der Server den Stream schließt – was vielleicht nie passiert –, und nimmt allein also dein ganzes Programm in Beschlag. Echte Clients wollen den Beobachter *neben* dem Hauptablauf: Ein Agent ruft Tools auf, während ein Beobachter einen Cache oder eine UI aktuell hält.

Öffne zuerst das Abonnement, starte dann den Beobachter und mach mit deiner Arbeit weiter.

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` importiert `BOARD` und `read_board` aus dem ersten Beispiel, das dieses Repo als
    `tutorial003.py` speichert. Wenn du die gerenderten Dateien nebeneinander als `client.py` und `app.py`
    ablegst, schreibe stattdessen `from client import BOARD, read_board`. Das Beispiel `watch.py` weiter unten
    importiert `read_board` auf dieselbe Weise.

Auf die Reihenfolge kommt es an. Nichts wird erneut abgespielt, ein Event, das veröffentlicht wurde, bevor dein Stream existierte, geht also verloren. Das Betreten von `client.listen(...)` wartet auf die Bestätigung, sodass jede Änderung ab diesem Moment deinen Beobachter erreicht und der Snapshot, den du im Block aufnimmst, keine verpassen kann.

Requests laufen ungehindert neben einem offenen Stream, aus dem Beobachter-Task oder jedem anderen, auf demselben Client. Weil *doppelte* unverarbeitete Events zusammenfallen, kann ein beschäftigter Hauptablauf ein einziges erneutes Abrufen auslösen statt drei. Unterschiedliche Events fallen nicht zusammen: Ein Filter, der viele URIs nennt, reiht pro URI ein ausstehendes Event ein.

Um das Beobachten zu beenden, verlässt du den Block: Einen `unsubscribe`-Aufruf gibt es nicht. Das Abbrechen des Tasks, dem der Block gehört, erledigt das für dich, und das SDK bricht den listen-Request so ab, wie der Transport es erwartet: über Streamable HTTP durch Schließen des Streams dieses Requests. Ein Beobachter, der für die Lebensdauer deiner App läuft, kehrt nie von selbst zurück, brich ihn also beim Herunterfahren ab – oder den Scope seiner Task-Gruppe.

## Streams enden {#streams-end}

Ein Stream endet auf eine von zwei Arten, beide sind gewöhnlicher Kontrollfluss. Ein geordnetes Schließen durch den Server beendet das `async for`; ein abrupter Abbruch löst `SubscriptionLost` aus.

Der Unterschied ist diagnostisch, kein Unterschied darin, was als Nächstes zu tun ist: Der Stream ist weg, nichts wurde erneut abgespielt, und ein Beobachter, dem es noch wichtig ist, lauscht erneut und ruft erneut ab.

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

Server schließen Streams aus eigenen Gründen geordnet, etwa um einen Abonnenten loszuwerden, dessen Rückstand zu groß geworden ist. Ein sauberes Ende ist also kein Signal, mit dem Beobachten aufzuhören. Warte ab (Backoff), bevor du erneut lauschst.

`SubscriptionLost` hat auch eine lokale Ursache. Der Client hält höchstens 1024 unverarbeitete Events, und ein Verbraucher, der so weit zurückfällt, verliert das Abonnement, statt unbegrenzt zu wachsen. Halte den Rumpf des `async for` kurz und erledige langsame Arbeit anderswo.

`keep_following` fängt nur `SubscriptionLost` ab. Das Betreten von `listen()` kann außerdem `MCPError` auslösen (die Verbindung ist fehlgeschlagen, oder der Server bedient die Methode nicht), `TimeoutError` (keine Bestätigung kam an) und `ListenNotSupportedError` (eine Verbindung von vor 2026). Entscheide, bei welchen davon dein Beobachter es erneut versuchen sollte: Der letzte heilt nie.

## Zusammenfassung {#recap}

* Betritt `async with client.listen(...)`; das Betreten wartet auf die Bestätigung, sodass nichts verpasst wird, was danach veröffentlicht wird.
* Iteriere mit `async for event in sub`. Events sind Stichworte zum erneuten Abrufen, nie Payloads.
* Öffne das Abonnement, führe dann den Beobachter als Task aus, und Tool-Aufrufe fließen daneben weiter.
* Ein sauberes Ende stoppt die Schleife; ein Abbruch löst `SubscriptionLost` aus. So oder so: erneut lauschen, erneut abrufen, vorher abwarten.
* Das Verlassen des Blocks ist das Abbestellen.

Diese Events veröffentlichen, den Filter eingrenzen und über einen Prozess hinaus skalieren sind die Geschichte des Servers: **[Abonnements](../handlers/subscriptions.md)**. Dieselben Events halten auch einen clientseitigen Cache ehrlich, und **[Caching](caching.md)** ist die nächste Seite.
