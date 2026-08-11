---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# Caching-Hinweise {#caching-hints}

Jedes Ergebnis, das ein Server für `tools/list`, `prompts/list`, `resources/list`, `resources/templates/list`, `resources/read` und `server/discover` zurückgibt, trägt im Protokoll 2026-07-28 zwei Felder: `ttlMs`, wie viele Millisekunden ein Client das Ergebnis als frisch behandeln darf, und `cacheScope`, ob ein gecachtes Ergebnis personenübergreifend geteilt werden darf (`"public"`) oder zu genau einem Autorisierungskontext gehört (`"private"`).

Der Server cacht selbst nichts. Die Felder sind eine *Erklärung*: „Diese Tool-Liste ist für alle gleich und ändert sich eine Minute lang nicht.“ Ein Client (oder ein Gateway vor deinem Server) kann sich dann den Roundtrip sparen. Ob er die Hinweise beachtet, entscheidet der Client; sie auszugeben ist Aufgabe des Servers, und das übernimmt das SDK für dich.

Ohne weitere Konfiguration sagt jedes Ergebnis `ttlMs: 0, cacheScope: "private"`: sofort abgelaufen, nie geteilt. Das ist immer sicher und immer protokollkonform. Wenn deine Listen tatsächlich stabil und für alle Aufrufer identisch sind, gib das bei der Konstruktion an:

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* Die Map ist nach **Methodennamen** geschlüsselt, und die sechs cachefähigen Methoden sind die einzigen zulässigen Schlüssel. Der Parameter ist als `Mapping[CacheableMethod, CacheHint]` typisiert, sodass dein Editor die Schlüssel automatisch vervollständigt und einen Tippfehler markiert, bevor du den Code ausführst; was am Typprüfer vorbeirutscht, löst bei der Konstruktion eine Exception aus.
* Eine Methode, die du nicht erwähnst, behält die Standardwerte. Die Map ist eine Sammlung von Überschreibungen, kein Manifest.
* `CacheHint(ttl_ms=5_000)` lässt `scope` ungesetzt, also bleibt es `"private"`: fünf Sekunden Frische, pro Aufrufer. Scope und TTL sind unabhängige Entscheidungen.
* `"server/discover"` ist ebenfalls ein zulässiger Schlüssel, denn das Discovery-Ergebnis ist cachefähig wie jede Liste.

!!! warning
    `cacheScope: "public"` heißt: Deine gecachte Response darf an *alle* ausgeliefert werden. Ein
    gemeinsam genutztes Gateway reicht das Ergebnis einer Person ohne Zögern an eine andere weiter,
    selbst wenn der Request authentifiziert war. Markiere ein Ergebnis nur dann als `"public"`, wenn
    es für alle Aufrufer identisch ist, und verwende `cacheScope` nie als Zugriffskontrolle: Es ist
    ein Etikett, kein Schloss.

## Überschreiben pro Handler {#per-handler-override}

Auf dem Low-Level-`Server` bauen Handler ihre Ergebnisse von Hand, und `ttl_ms` / `cache_scope` sind einfach Felder der Ergebnismodelle. Ein Handler, der sie explizit setzt, gewinnt immer gegen die Map aus dem Konstruktor, Feld für Feld:

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

Der Handler hat `ttl_ms=1_000` gesetzt und nichts zum Scope gesagt. Auf der Leitung: `ttlMs: 1000` (vom Handler, nicht die `60_000` der Map) und `cacheScope: "public"` (aus der Map, weil der Handler es ungesetzt ließ). Explizit schlägt konfiguriert, und konfiguriert schlägt Standardwert. Das gilt pro Feld, ein Handler kann also ein Feld festlegen und das andere der serverweiten Richtlinie überlassen.

Das ist auch der Notausgang für Dynamik, die der Konstruktor nicht kennen kann: Ein Handler, der `resources/read` pro Person filtert, kann auf einem ansonsten öffentlichen Server für einen URI `cache_scope="private"` zurückgeben.

Ein Vorbehalt bei paginierten Listen: Das Protokoll verlangt **denselben `cacheScope` auf jeder Seite** einer Liste. Die Map aus dem Konstruktor erfüllt das von selbst, weil sie nach Methode geschlüsselt ist, nicht nach Seite. Ein Handler, der den Scope selbst überschreibt, ist aber auch selbst für diese Konsistenz verantwortlich: Überschreibe ihn auf *jeder* Seite, nie nur dann, wenn ein Cursor vorhanden ist, sonst widersprechen sich Seite eins und Seite zwei.

## Was der Client sieht {#what-the-client-sees}

In einer 2026-07-28-Session beachtet `Client` die Hinweise für dich: Er hat einen eingebauten Response-Cache, der standardmäßig aktiv ist. Ein Ergebnis, das mit einem `ttlMs` ankommt, wird gespeichert, und ein identischer Aufruf innerhalb dieser TTL wird ohne Roundtrip aus dem Cache bedient. Ein Ergebnis, das *keinen* Hinweis trägt, wird nicht gecacht: Ergebnisse ohne Hinweis bekommen `CacheConfig.default_ttl_ms`, dessen Standardwert `0` ist (sofort abgelaufen), sodass ein Server, der nichts deklariert, Aufruf für Aufruf genau denselben Verkehr sieht wie schon immer.

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

Vier Aufrufe, drei Abrufe. Der zweite Aufruf fand einen frischen Eintrag und erreichte den Server nie; die (injizierte) Uhr über die TTL hinaus vorzustellen ließ den dritten wieder abrufen; der vierte gab `cache_mode="refresh"` an. Dieses Keyword-Argument gibt es auf den fünf cachenden Verben (`list_tools`, `list_prompts`, `list_resources`, `list_resource_templates`, `read_resource`):

* `"use"` (der Standardwert) liefert einen frischen Eintrag, wenn es einen gibt, und speichert andernfalls den Abruf.
* `"refresh"` liefert nie aus dem Cache: Es ruft ab und speichert das Ergebnis, wobei es ersetzt, was auch immer gecacht war.
* `"bypass"` macht den Roundtrip, ohne den Cache überhaupt anzufassen: kein Lesen, kein Schreiben.

Eine Regel steht über `"use"`: **Aufrufe mit `meta` erreichen immer den Server.** Ein Request mit gesetztem `meta` (ein Progress-Token, Tracing-Felder) erwartet einen Request auf der Leitung, deshalb wird er unter `cache_mode="use"` wie `"refresh"` behandelt: Das Lesen aus dem Cache entfällt, und das abgerufene Ergebnis ersetzt trotzdem den gecachten Eintrag. `"bypass"` und ein explizites `"refresh"` verhalten sich wie immer.

Um das Caching ganz abzuschalten, konstruiere mit `Client(server, cache=None)`: Jeder Aufruf ist wieder ein Roundtrip, und `cache_mode` wird zwar weiter akzeptiert, bewirkt aber nichts.

Auch der Scope wird automatisch beachtet: `"private"`-Einträge sind an die *Partition* des Caches gebunden (siehe unten), während `"public"`-Einträge sich für breiteres Teilen entscheiden können. Und **Benachrichtigungen schlagen die TTL** für genau die Einträge, die sie benennen: Eine `list_changed`-Benachrichtigung verdrängt die passende gecachte Liste, und `resources/updated` verdrängt den gecachten Lesevorgang, der unter exakt ihrem URI gespeichert ist – egal, wie frisch sie waren. Auf einer 2026-07-28-Verbindung kommen diese Benachrichtigungen auf einem `subscriptions/listen`-Stream an, den du mit `client.listen(...)` öffnest, und die Verdrängung ist abgeschlossen, bevor dein Watcher das Ereignis sieht; alles dazu steht in **[Abonnements](subscriptions.md)**.

Ein Vorbehalt bei `resources/updated`: Verdrängt wird nur bei exakt gleichem URI. Der Store-Vertrag kennt keine Operation zum Aufzählen oder Scannen (wie auch die TypeScript-Referenzimplementierung), daher verdrängt eine Benachrichtigung mit dem URI einer *Unter*-Ressource keinen gecachten Lesevorgang ihrer übergeordneten Ressource. Wenn dein Server Unter-Ressourcen so signalisiert, rufe die übergeordnete Ressource mit `cache_mode="refresh"` erneut ab.

### Konfiguration: `CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`: wo die Einträge liegen. Standardmäßig ist das ein frischer In-Memory-Store pro Client; übergib deine eigene `ResponseCacheStore`-Implementierung (etwa mit Redis dahinter), um einen Cache über Clients oder Prozesse hinweg zu teilen. Die Vertragstypen (`ResponseCacheStore`, `CacheKey`, `CacheEntry` und der Standard-`InMemoryResponseCacheStore`) lassen sich aus `mcp.client` importieren. Ein Lookup kann bis zu zwei aufeinanderfolgende `get`s am Store auslösen (erst den privaten Zweig, dann den öffentlichen), plane die Latenzerwartungen an einen entfernten Store also entsprechend. Ein eigener Store **erfordert** eine explizite `partition`.
* `partition`: das Label für den Autorisierungskontext, das verhindert, dass die `"private"`-Einträge eines Principals in einem gemeinsam genutzten Store an einen anderen ausgeliefert werden.
* `target_id`: explizite Server-Identität, für eigene Transporte und In-Process-Server (siehe unten).
* `default_ttl_ms`: TTL für Ergebnisse, die keinen `ttlMs`-Hinweis tragen. Der Standardwert `0` lässt Ergebnisse ohne Hinweis ungecacht.
* `share_public`: vom Server als `"public"` deklarierte Einträge über Partitionen hinweg ausliefern (siehe unten). Standardmäßig aus.
* `clock`: die Quelle für die Uhrzeit, in Epoch-Sekunden. Injiziere eine, wie es das Beispiel oben tut, und Ablauftests kommen ohne Schlafen aus.

!!! warning "Partition = verifizierter Principal"
    Leite `partition` aus einem **verifizierten Credential** ab, etwa dem Subject eines validierten Tokens. Leite sie nie aus Daten ab, die der Request mitliefert, und nie aus der Server-URL (die Server-Identität ist eine eigene Schlüsselachse). Das SDK ist eine Bibliothek ohne eigene Authentifizierung: Der Vertrauensanker ist, wer auch immer die `CacheConfig` konstruiert – also das Deployment, nicht der Mandant. Ein mandantenfähiges Gateway erzeugt eine `CacheConfig` pro authentifiziertem Principal.

    Die Partition steht außerdem für die Lebensdauer des `Client` fest. Ändert sich der Autorisierungskontext der Verbindung mitten in der Session (etwa durch erneute Authentifizierung als anderer Principal), folgt der Cache nicht; konstruiere einen neuen `Client` für den neuen Principal.

Cache-Schlüssel tragen außerdem die **Identität des Servers**: den URL-String, den du angewählt hast, ohne etwaige `user:pass@`-Userinfo und ansonsten bytegenau. Keine Normalisierung der Groß-/Kleinschreibung, keine Umsortierung der Query, kein Bereinigen abschließender Schrägstriche. Zu wenig Normalisierung kostet nur Teilbarkeit, zu viel könnte zwei Mandanten zusammenlegen (`?tenant=a` gegenüber `?tenant=b`), deshalb teilen oberflächlich verschiedene URLs einfach keine Einträge. Gibt es keine URL (ein In-Process-Server oder eine `Transport`-Instanz), bekommt der Client stattdessen eine zufällige Identität pro Instanz; setze `CacheConfig.target_id`, um den Server zu benennen (bei einem eigenen Store ist das Pflicht, und die Konstruktion sagt dir das). Die Identität wird mit sha256 gehasht, bevor sie ins Schlüsselmaterial eingeht, sodass eine URL mit Geheimnissen im Query-String nie in Store-Schlüsseln auftaucht. Logge die Form vor dem Hashing auch selbst nicht.

!!! warning "`share_public` vertraut dem Server, flottenweit"
    Standardmäßig bleiben selbst `"public"`-Einträge in ihrer Partition. `share_public=True` liefert Einträge, die der Server mit `cacheScope: "public"` markiert hat, an **jede** Partition aus, die den Store nutzt, und vertraut dabei im Namen aller auf die Einstufung des Servers. Ein Server, der mandantenspezifische Daten als `"public"` stempelt (aus Versehen oder in böser Absicht), lässt dann die Response eines Mandanten zu den anderen durchsickern. Das Flag gibt es bewusst nur auf Konstruktorebene: Das `cache_mode` pro Aufruf kann das Caching einschränken, aber nichts pro Aufruf kann das Teilen ausweiten.

### Was der Cache nie tut {#what-the-cache-never-does}

* **Aufrufe auf Session-Ebene umgehen ihn.** `client.session.list_tools()` und Konsorten machen immer den Roundtrip; der Cache sitzt auf den `Client`-Verben.
* **`server/discover` bleibt außen vor.** Das Discover-Ergebnis wird einmal geliefert, beim Verbinden, und gelangt nie in den Response-Cache, selbst wenn es ein `ttlMs` trägt. Wenn du selbst eines persistierst, um die Probe beim Wiederverbinden zu überspringen ([`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)), ist seine Frische deine eigene Buchführung: `DiscoverResult` trägt `ttl_ms` und `cache_scope`, bereits geparst, genau zu diesem Zweck.
* **Folgeseiten werden nie gecacht.** Nur Aufrufe ohne Cursor nehmen teil. Eine Folgeseite, die wegen eines abgelaufenen Cursors abgelehnt wird, *verdrängt* allerdings die gecachte Liste, weil sich die Liste darunter geändert hat.
* **Multi-Roundtrip-Lesevorgänge (multi-round-trip reads) werden nie gecacht.** Ein `read_resource`, das mit `input_responses`/`request_state` gestartet wird oder das über Eingaberunden aufgelöst wird, gelangt nie in den Cache (ein MUST der Spezifikation).
* **Verdrängung per Benachrichtigung braucht Benachrichtigungen.** Die Verdrängung ist nur so gut wie die Zustellung durch den Transport, und der moderne In-Process-Pfad (`Client(server)` mit dem Standardwert `mode="auto"`) stellt heute keine eigenständigen Benachrichtigungen zu.
* **Verdrängung geschieht letztendlich, nicht augenblicklich.** Benachrichtigungen vom Leitungspfad werden aus eigens gestarteten Tasks verteilt, sodass ein Aufruf, der mit dem Eintreffen einer Benachrichtigung um die Wette läuft, noch einmal den Eintrag von vor der Verdrängung bekommen kann; das Fenster ist durch die Dispatch-Latenz begrenzt, und die Verdrängung kommt trotzdem an.
* **Kein Stale-if-error.** Ein abgelaufener Eintrag wird nie deshalb ausgeliefert, weil der erneute Abruf fehlschlug; der Fehler wird weitergereicht.
* **Kein vorzeitiger Neuabruf.** Ein gespeicherter Eintrag wird ausgeliefert, bis seine TTL abläuft, und der nächste Aufruf danach bezahlt den Roundtrip; nichts wird im Hintergrund aktualisiert.
* **Kein Zusammenfassen.** Zwei gleichzeitige identische Aufrufe sind zwei Abrufe.
* **Keine TTL über 24 Stunden.** Ein größeres `ttlMs`, ob vom Server gesendet oder konfiguriert, wird beim Speichern gekappt (`mcp.client.caching.MAX_TTL_MS`); das begrenzt, wie lange irgendein Eintrag ausgeliefert werden kann, egal wie großzügig der Hinweis war.
* Auf einem **gemeinsam genutzten Store** laufen Clients gegeneinander um die Wette. Jeder Client verwirft seinen eigenen Schreibvorgang, wenn eine Verdrängung den laufenden Abruf überholt hat, aber ein Client eines *Mit-Mandanten* kann trotzdem einen Eintrag zurückschreiben, den eine Verdrängung entfernt hatte, die er nie gesehen hat; und diese Race-Buchführung ist selbst begrenzt: Jenseits von 4096 verfolgten Schlüsseln wird zuerst der Schutz des ältesten Schlüssels verworfen. Beide Fenster sind akzeptiert und werden durch die TTL-Obergrenze oben geschlossen.
* **Kein Ausliefern über Protokollgenerationen hinweg.** Einträge sind auf die ausgehandelte Protokollversion beschränkt: Auf einem gemeinsam genutzten persistenten Store liefert eine Session nie einen Eintrag aus, der unter einer anderen ausgehandelten Version geschrieben wurde (dieselbe Liste unterscheidet sich tatsächlich je nach Generation, weil das SDK die 2026er-Felder für ältere Sessions entfernt). Verdrängung berührt ebenso nur die Einträge der aktuellen Generation; Einträge einer anderen Generation laufen einfach per TTL ab.

### Die Hinweise selbst lesen {#reading-the-hints-yourself}

Die Hinweise sind außerdem ganz normale Felder auf jedem cachefähigen Ergebnis (`result.ttl_ms` und `result.cache_scope`, bereits geparst), falls du eine eigene Buchführung über den eingebauten Cache legen willst (oder an seiner Stelle).

Gegenüber einem **älteren Server** (Protokoll vor 2026) fehlen die Felder auf der Leitung einfach, und die Modelle zeigen ihre konservativen Standardwerte: `ttl_ms == 0` und `cache_scope == "private"`, abgelaufen und ungeteilt – die richtige Annahme für einen Server, der nichts deklariert hat. Der Cache behandelt eine Legacy-Session genauso: Hinweise werden dort nie herangezogen (egal welche Schlüssel auf der Leitung auftauchen), es gilt nur `default_ttl_ms`, und dessen Standardwert `0` cacht nichts, sodass sich eine Verbindung vor 2026 genau so verhält wie vor der Existenz des Caches. Musst du „der Server hat 0 gesagt“ von „der Server hat nichts gesagt“ unterscheiden, prüfe `"ttl_ms" in result.model_fields_set`: Das ist nur gesetzt, wenn das Feld tatsächlich angekommen ist.

## Ältere Clients {#older-clients}

Clients mit Protokollversionen vor 2026 sehen keines der beiden Felder; das SDK entfernt sie für diese Verbindungen bei der Serialisierung. Konfiguriere deine Hinweise einmal; es gibt nichts Versionsspezifisches zu schreiben.

## Zusammenfassung {#recap}

* Sechs Methoden tragen `ttlMs`/`cacheScope`; das SDK setzt sie standardmäßig auf `0`/`"private"` – abgelaufen und ungeteilt, immer sicher.
* `cache_hints={method: CacheHint(...)}` bei der Konstruktion (sowohl `MCPServer` als auch `Server`) setzt serverweite Werte pro Methode.
* Ein Handler, der die Felder auf seinem Ergebnis setzt, überschreibt die Map, pro Feld.
* `"public"` ist ein Versprechen, dass das Ergebnis für alle Aufrufer identisch ist. Es ist keine Zugriffskontrolle.
* `Client` beachtet die Hinweise automatisch: Sein Response-Cache ist standardmäßig aktiv, liefert frische Einträge statt neu abzurufen und cacht nichts für Server (oder Sessions), die keine Hinweise liefern.
* Pro Aufruf ruft `cache_mode="refresh"` neu ab und `"bypass"` umgeht den Cache; `cache=None` bei der Konstruktion schaltet ihn ganz ab.
