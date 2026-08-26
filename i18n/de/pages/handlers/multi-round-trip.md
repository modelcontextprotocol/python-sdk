---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# Multi-Roundtrip-Requests {#multi-round-trip-requests}

Manchmal kann ein Tool nicht in einem einzigen Roundtrip fertig werden. Es braucht etwas, das nur die Person am Host hat: eine Auswahl, eine Bestätigung, Zugangsdaten.

Vor 2026-07-28 holte der Server sich das, indem er **zurückrief**: Mitten in der Bearbeitung des ursprünglichen Requests öffnete er einen eigenen Request an den Client (eine Elicitation – also eine Rückfrage bei der Person am Host – oder einen Sampling-Aufruf). Die Spec 2026-07-28 schafft diesen Rückkanal (back-channel) ab.

Stattdessen **gibt** der Server etwas **zurück**.

## Zurückgeben statt zurückrufen {#return-dont-call-back}

Der Server beantwortet `tools/call` mit einem **`InputRequiredResult`** statt mit einem `CallToolResult`. Zwei seiner Felder erledigen die Arbeit:

* **`input_requests`**: was der Server noch braucht, als Dict mit Schlüsseln, die der Server selbst gewählt hat. Jeder Wert ist ein `ElicitRequest`, ein `CreateMessageRequest` oder ein `ListRootsRequest`.
* **`request_state`**: ein opakes Token. Der Client schickt es beim Retry unverändert zurück. Dein Server ist der Einzige, der es liest.

Der Client erfüllt jeden Request und ruft dann **dasselbe Tool noch einmal** auf, mit seinen Antworten in `input_responses` und dem Token in `request_state`. Der Server hat jetzt, was ihm fehlte, und gibt ein normales `CallToolResult` zurück.

Das ist das ganze Protokoll. Jede Etappe ist ein gewöhnlicher Request vom Client an den Server. Nie fließt etwas in die andere Richtung.

## Die Serverseite {#the-server-side}

Auf `@mcp.tool()` baust du das selten von Hand: Deklariere eine Abhängigkeit, die bei der Person am Host zurückfragt (`Elicit`), das LLM des Clients per Sampling nutzt (`Sample`) oder seine Roots auflistet (`ListRoots`), und das SDK gibt das `InputRequiredResult` für dich zurück; diese Form beschreibt die Seite **[Abhängigkeiten](dependencies.md)**. Die beiden Formen lassen sich nicht mischen: Ein Aufruf hat genau einen `input_responses`/`request_state`-Kanal, deshalb kann ein Tool, das `Resolve(...)`-Parameter verwendet, nicht zusätzlich ein `InputRequiredResult` aus seinem Rumpf zurückgeben. Ein deklarierter `InputRequiredResult`-Rückgabetyp wird bei der Registrierung abgelehnt (`InvalidSignature`), ein nicht deklarierter lässt den Aufruf zur Laufzeit fehlschlagen. Die manuelle Form ist der **Low-Level**-`Server`, dessen Handler `on_call_tool` beide Ergebnistypen zurückgeben darf:

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` ist typisiert als `-> CallToolResult | InputRequiredResult`. Das zweite zurückzugeben ist die gesamte serverseitige API.
* Beim ersten Aufruf ist `params.input_responses` `None`, also greift die Guard-Bedingung, und der Handler fragt, statt zu antworten.
* Beim Retry liegt das `ElicitResult`, das der Client geschickt hat, unter **demselben Schlüssel** (`"region"`), den der Server in `input_requests` verwendet hat.

Alles andere in dieser Datei (das explizite `input_schema`, das von Hand gebaute `CallToolResult`) ist der gewöhnliche Low-Level-`Server`, behandelt in **[Der Low-Level-Server](../advanced/low-level-server.md)**. Diese Seite fügt nur den zweiten Rückgabetyp hinzu.

## Über Tools hinaus {#beyond-tools}

`tools/call` ist nichts Besonderes: Unter 2026-07-28 darf ein Server `prompts/get` und `resources/read` genauso beantworten. Auf `MCPServer` gibt eine `@mcp.prompt()`-Funktion – oder eine `@mcp.resource()`-**Template**-Funktion – das `InputRequiredResult` selbst zurück und liest die Antworten des Retrys aus dem Context:

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* Die erste Runde gibt das `InputRequiredResult` zurück. Beim Retry hält `ctx.input_responses` die Antworten unter denselben Schlüsseln bereit, und die Funktion gibt ihr gewöhnliches Ergebnis zurück – hier Prompt-Nachrichten, bei einer Template-Ressource Ressourceninhalt.
* Ein `request_state`, den du setzt, wird versiegelt, bevor er über die Leitung geht, und beim Echo verifiziert, wie alles andere auf dem Server; **[`requestState` schützen](#protecting-requeststate)** weiter unten beschreibt, was dir das Siegel bringt und wann du Schlüssel konfigurieren musst.
* Eine `@mcp.tool()`-Funktion kann das Ergebnis genauso direkt zurückgeben, wenn die Abhängigkeitsform nicht passt.
* Statische `@mcp.resource()`-Funktionen nehmen nicht teil: Sie bekommen keinen `Context` und könnten den Retry deshalb nie lesen. Nur Template-Ressourcen können fragen.
* Die Regeln zur Protokollgeneration weiter unten gelten unverändert: Ein `InputRequiredResult` auf einer Session vor 2026 zurückzugeben, ergibt denselben `-32603`, den die Warnung beschreibt.

## Die Clientseite {#the-client-side}

`Client` führt die Schleife für dich aus.

Registriere die Callbacks, nach denen der Server fragen könnte (`elicitation_callback`, `sampling_callback`, `list_roots_callback`), und rufe das Tool auf. Kommt ein `InputRequiredResult` an, verteilt `Client` jeden Eintrag in `input_requests` an den passenden Callback, wiederholt den Aufruf mit den Antworten und dem zurückgeschickten `request_state` und macht weiter, bis ein `CallToolResult` zurückkommt:

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* Dieser `elicitation_callback` ist derselbe, den das `elicitation/create` eines Servers vor 2026 über den Rückkanal getroffen hätte. Dasselbe gilt für `sampling_callback` bei `sampling/createMessage` und für `list_roots_callback` bei `roots/list`: Unter 2026-07-28 sind die eigenständigen Server->Client-RPCs verschwunden, aber die identischen Payloads `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` reisen in `input_requests` mit und landen bei denselben drei Callbacks. Ein Satz Callbacks bedient beide Generationen.
* `call_tool` gibt ein schlichtes `CallToolResult` zurück. Die Zwischenrunden sind für den aufrufenden Code unsichtbar.
* `get_prompt` und `read_resource` treiben dieselbe Schleife.

!!! check
    Lässt du den Callback weg, scheitert die Schleife in der ersten Runde: Der Ersatz-Callback des SDK
    beantwortet jede Elicitation mit einem Fehler, und `call_tool` löst `MCPError` mit der Meldung
    *„Elicitation not supported“* aus.

Die Schleife ist begrenzt. `Client(..., input_required_max_rounds=10)` ist die Standardobergrenze; ein Server, der darüber hinaus weiter `InputRequiredResult` zurückgibt, lässt `call_tool` eine Exception auslösen. Trägt eine Runde nur `request_state` und keine `input_requests`, schläft `Client` kurz (50 ms, verdoppelt bis zu einer Obergrenze von 250 ms), bevor er es erneut versucht. So wird ein Server, der nur *„noch nicht fertig“* sagt, nicht in einer Dauerschleife abgefragt.

### Die Schleife selbst steuern {#driving-the-loop-yourself}

Die automatische Schleife genügt für einen Client in einem einzigen Prozess. Übernimm die Schleife stattdessen selbst, wenn:

* dein Client **verteilt** ist: Der Prozess, der der Person die Frage anzeigt, ist nicht der Prozess, der `call_tool` aufgerufen hat, also setzt ein anderer Worker den Retry ab. `request_state` ist das persistierbare Token, das du über diese Grenze trägst – durch deinen eigenen Speicher –, und `input_responses` ist das, was die andere Seite damit zurückschickt.
* du jede Runde **inspizieren** willst: jeden `input_requests`-Eintrag loggen oder auditieren, bestimmte Request-Arten ablehnen oder zwischen den Etappen ein eigenes Backoff anwenden.
* du eine Grenze nach **Uhrzeit** statt nach Rundenzahl willst: Umschließe deine eigene Schleife mit `anyio.fail_after(...)`, statt dich auf `input_required_max_rounds` zu verlassen.

Geh auf die darunterliegende Session hinunter, wo `allow_input_required=True` dir die Union direkt aushändigt:

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` erweitert den Rückgabetyp auf `CallToolResult | InputRequiredResult`. Das `isinstance` engt ihn wieder ein.
* `request_state` liegt jetzt in deiner Hand. Schreib ihn zwischen den Etappen weg, und das Gespräch kann aus einem frischen Prozess fortgesetzt werden.
* Für jeden Eintrag in `input_requests` legst du eine `InputResponse` unter **demselben Schlüssel** in `input_responses` ab. `fulfil` ist die Stelle für deine UI; diese hier kodiert die Antwort fest.
* Derselbe Tool-Name, dieselben `arguments`, in jeder Etappe. Der Retry ist der ursprüngliche Aufruf, noch einmal ausgeführt, keine neue Methode.

## `requestState` schützen {#protecting-requeststate}

Alles oben behandelt `request_state` als Echo, und auf der Leitung ist er auch nichts anderes. Aber der Client hält ihn zwischen den Etappen (ihn über Prozesse hinweg wegzuschreiben ist genau das, was der vorige Abschnitt abgesegnet hat), also ist das, was zurückkommt, **vom Client gelieferte Eingabe**: Sie kann verändert, abgelaufen oder aus einem ganz anderen Aufruf entnommen sein. Die Spec verlangt von Servern, die Integrität dieses Zustands zu schützen und die Runde abzulehnen, wenn die Verifikation fehlschlägt – immer dann, wenn der Zustand Autorisierung, Ressourcenzugriff oder Geschäftslogik beeinflussen kann.

`MCPServer` schützt ihn standardmäßig. Jeder Server versiegelt ausgehenden `requestState` und verifiziert jedes Echo – Resolver-Zustand und von Hand gebauten Zustand gleichermaßen – unter einem Schlüssel, der beim Prozessstart erzeugt wird. Du konfigurierst nichts, schreibst Klartext und liest Klartext; über die Leitung geht immer nur ein opakes, verschlüsseltes Token.

Der Standardschlüssel lebt und stirbt mit dem Prozess – das ist das Eine, was du wissen musst, bevor du über einen einzelnen Prozess hinaus bereitstellst:

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **Der Standard (keine Konfiguration)** passt für einen einzelnen Prozess: stdio oder genau ein HTTP-Worker. Ein Retry, der bei einem anderen Worker, einer anderen Instanz hinter einem Load Balancer oder demselben Server nach einem Neustart landet, ist unter einem Schlüssel versiegelt, den dieser Prozess nicht hat – der Client bekommt die unten beschriebene feste Ablehnung und muss den Ablauf von vorn beginnen.
* **`keys=[...]`** ist erforderlich, sobald ein Retry eine **andere Instanz** erreichen kann (`uvicorn` mit mehreren Workern, HTTP hinter Lastverteilung) oder Neustarts überleben muss: Jede Instanz verifiziert, was irgendeine Schwesterinstanz ausgestellt hat. Dieselbe Maschinerie, dein Geheimnis statt eines erzeugten.
* Für eigene Kryptografie, etwa ein KMS oder einen vorhandenen Token-Dienst, übergib `RequestStateSecurity(codec=...)` statt `keys`; **[Eigene Kryptografie mitbringen](#bring-your-own-crypto)** weiter unten beschreibt den Vertrag.

### Was das Siegel trägt {#what-the-seal-carries}

Ob Standard oder konfiguriert: `requestState` auf der Leitung ist ein verschlüsseltes, authentifiziertes Token. Dein Code sieht es nie: Handler und Resolver schreiben Klartext und lesen Klartext (`ctx.request_state`); das SDK versiegelt auf dem Weg hinaus und verifiziert auf dem Weg hinein. Über die Integrität hinaus ist jedes Token gebunden an:

* **Ein Zeitfenster.** Jede Runde versiegelt neu mit frischem Ablaufzeitpunkt, deshalb begrenzt `RequestStateSecurity(ttl=...)` (Standardwert 600 Sekunden) die Bedenkzeit pro Runde, nicht den ganzen Ablauf.
* **Den authentifizierten Principal.** Trägt der Request ein OAuth-Access-Token, das das SDK validiert hat, wird der Zustand an Client, Issuer und Subject des Tokens gebunden: Zustand, der für eine Person ausgestellt wurde, scheitert unter einer anderen, selbst wenn beide denselben OAuth-Client teilen. Ein Verifier, der kein Subject liefert, schwächt die Bindung auf die Client-Identität allein ab, die bei URL-basierten Client-IDs alle teilen, die diese Client-Software verwenden. Wird die Authentifizierung außerhalb des SDK terminiert (ein vorgeschalteter Proxy) oder ist der Transport nicht authentifiziert, gibt es keinen Principal zum Binden, und diese Prüfung bleibt wirkungslos – es sei denn, `RequestStateSecurity(bind_principal=...)` liefert einen aus deinem eigenen Identitätssignal. Welche Bestandteile dein Token-Verifier auch liefert, er muss sie konsistent liefern: Ein Verifier, der das Subject bei manchen Requests einschließt und bei anderen weglässt, ändert den Principal mitten im Ablauf, und laufende Runden werden abgelehnt.
* **Den auslösenden Request.** Die Methode, den Tool- oder Prompt-Namen (oder den Ressourcen-URI) und einen Digest der Argumente. Ein Token, das gegen ein anderes Tool, andere Argumente oder eine andere Methode wieder eingespielt wird, scheitert.
* **Die genaue gestellte Frage.** Jede Resolver-Antwort ist an die gerenderte Frage geheftet, die dem Client gezeigt wurde, sowohl in der Runde, in der sie zuerst eintrifft, als auch wenn eine aufgezeichnete Antwort später wiederverwendet wird. Stellst du mit umformulierter Nachricht oder geändertem Schema neu bereit, fragt der Server erneut, statt eine veraltete Antwort zu verbrauchen. Dieselbe Bindung wirkt auch andersherum: Leite Nachrichten aus den Argumenten des Tools ab, nicht aus Daten pro Aufruf. Eine Nachricht, die aus einem Zeitstempel oder einem Live-Kurs gebaut ist, rendert in jeder Runde anders, sodass jede aufgezeichnete Antwort veraltet aussieht und der Server erneut fragt, bis das Rundenlimit des Clients den Aufruf beendet.

All das ist Aufgabe des SDK, nicht deine – und nicht die des Codecs, falls du deinen eigenen mitbringst.

### Schlüssel rotieren {#rotating-keys}

`keys[0]` versiegelt neuen Zustand; jeder Schlüssel in der Liste verifiziert. Eine Rotation ohne Ausfallzeit besteht aus drei Phasen, jede vollständig ausgerollt, bevor die nächste beginnt:

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

Befördere niemals zuerst den ausstellenden Schlüssel: Unter einem Schlüssel auszustellen, den manche Instanz noch nicht verifizieren kann, lässt laufende Runden mitten im Rollout fallen.

Schlüssel gelten für genau einen Dienst. Der versiegelte Umschlag trägt außerdem den Namen des Servers als Audience-Claim, sodass ein Token, das ein anderer Dienst ausgestellt hat, der zufällig ein Geheimnis teilt, trotzdem abgelehnt wird. Der Claim ist nur so unterscheidungskräftig wie der Name, deshalb muss ein Server mit expliziter Policy einen echten Namen haben oder `RequestStateSecurity(audience=...)` setzen – ein unbenannter löst bei der Konstruktion eine Exception aus. `audience=` dient auch bewussten Multi-Service-Topologien, in denen ein Dienst Zustand akzeptieren muss, den ein anderer ausgestellt hat. (Der konfigurationsfreie Standard ist ausgenommen: Sein Schlüssel verlässt den Prozess nie, also hat der Audience-Claim nichts hinzuzufügen.)

### Eigene Kryptografie mitbringen {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` nimmt alles mit `seal(bytes) -> str` und `unseal(str) -> bytes`, das für jedes Token, das es nicht selbst ausgestellt hat, `InvalidRequestState` auslöst. Die klassische Form ist Envelope Encryption gegen ein KMS, bei der du beim Start einmal einen Datenschlüssel entpackst und die Kryptografie pro Token lokal hältst:

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL, Principal-Bindung und Request-Bindung sind **nicht** Sache des Codecs: Das SDK stempelt sie vor `seal` in die Payload und verifiziert sie nach `unseal` erneut, für jeden Codec. Die einzigen Pflichten eines Codecs sind Integrität (manipuliert heißt: Exception auslösen) und idealerweise Vertraulichkeit.

### Wenn die Verifikation fehlschlägt {#when-verification-fails}

Jeder eingehende Fehlschlag – ob manipuliert, abgelaufen, gegen einen anderen Request oder Principal wieder eingespielt oder unter einem Schlüssel versiegelt, den dieser Server nicht kennt – bekommt dieselbe Antwort:

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

Eine feste Meldung für jede Ursache, damit die Leitung nie verrät, welche Prüfung fehlschlug; der wahre Grund geht ins Server-Log. Jeder eingehende `requestState` auf `tools/call`, `prompts/get` und `resources/read` wird geprüft, auch einer, der für einen Handler eintrifft, der nie Zustand ausstellt. Die in der Praxis häufigste Ablehnung ist kein Angriff – es ist der prozesslokale Standardschlüssel, der auf einen Retry von vor einem Neustart oder von einer anderen Instanz trifft; der Client startet den Ablauf neu, und `keys=[...]` ist die Lösung, wenn das ins Gewicht fällt.

### Von Hand gebauter Zustand {#hand-built-state}

Ein `request_state`, den du selbst setzt (indem du `InputRequiredResult` aus einer Tool-, Prompt- oder Ressourcen-Template-Funktion zurückgibst), wird von derselben Maschinerie versiegelt und verifiziert wie Resolver-Zustand, ganz ohne Codeänderungen: Klartext schreiben, Klartext lesen, und jede Bindung oben gilt.

Das Eine, was das SDK dir nicht festheften kann, selbst wenn konfiguriert, ist die Identität der Frage: Es weiß nicht, zu welcher *deiner* Fragen eine Antwort in deinem Zustand gehört. Speicherst du Antworten nach Fragen geschlüsselt, nimm deine eigene Fragekennung in den Zustand auf und prüfe sie beim Retry.

Der Low-Level-`Server` ist die Stufe ohne Extras: Anders als bei `MCPServer` wird nichts versiegelt, bis du die Grenze selbst anhängst, und bis dahin geht dein `request_state` genau so über die Leitung, wie du ihn geschrieben hast. Das einzeilige Opt-in zeigt **[Der Low-Level-Server](../advanced/low-level-server.md#the-other-handlers)**.

## Ein Ergebnis für 2026-07-28 {#a-2026-07-28-result}

`InputRequiredResult` gibt es nur bei Protokollversion **2026-07-28**. Der In-Memory-`Client(server)` handelt sie für dich aus; über die Leitung entdeckt `mode="auto"` sie. Nach dem Verbinden sagt dir `client.protocol_version`, was du bekommen hast.

!!! warning
    Eine Session vor 2026 hat keinen Platz für ein `InputRequiredResult`. Gibst du eines aus deinem Handler auf einer
    `mode="legacy"`-Verbindung zurück, kann der Runner es nicht in die ausgehandelte Version serialisieren; der
    Client bekommt einen `-32603`-Fehler *„Handler returned an invalid result“* zurück. Ein Server, der
    beide Generationen bedient, muss `ctx.protocol_version` prüfen, bevor er danach greift.

!!! info
    **Elicitation im URL-Modus** nutzt auf einer 2026er-Verbindung genau diesen Mechanismus. Der Eintrag in
    `input_requests` ist ein `ElicitRequest`, dessen Params `ElicitRequestURLParams` sind; die Person
    schließt den Out-of-band-Ablauf ab, und dein Client wiederholt den Aufruf. Dieselbe Schleife, keine neue API. Die
    Hälfte für den High-Level-Server steht in **[Elicitation](elicitation.md)**.

## Zusammenfassung {#recap}

* Unter 2026-07-28 **gibt** ein Server, der mitten im Aufruf Eingaben braucht, ein `InputRequiredResult` **zurück**. Er öffnet nie einen Request an den Client.
* `input_requests` ist, was er braucht. `request_state` ist ein opakes Wiederaufnahme-Token, das nur der Server liest.
* `Client` führt die Retry-Schleife für dich aus: Registriere `elicitation_callback` / `sampling_callback` / `list_roots_callback`, und `call_tool` gibt ein schlichtes `CallToolResult` zurück. `input_required_max_rounds` (Standardwert 10) begrenzt sie.
* Um Runden zu inspizieren oder zu persistieren, verwende `client.session.call_tool(..., allow_input_required=True)` und übernimm die Schleife `while isinstance(result, InputRequiredResult)` selbst.
* Auf `@mcp.tool()` erzeugt eine Abhängigkeit, die bei der Person am Host zurückfragt, dieses Ergebnis für dich (**[Abhängigkeiten](dependencies.md)**); der **Low-Level**-`Server` ist die manuelle Form.
* Prompts und Ressourcen nehmen ebenfalls teil: Eine `@mcp.prompt()`- oder Template-`@mcp.resource()`-Funktion gibt das `InputRequiredResult` selbst zurück und liest beim Retry `ctx.input_responses`.
* `requestState` kommt als vom Client gelieferte Eingabe zurück, deshalb versiegelt `MCPServer` ihn standardmäßig – Resolver-Zustand und von Hand gebauten Zustand gleichermaßen – unter einem prozesslokalen Schlüssel; Deployments mit mehreren Instanzen übergeben `RequestStateSecurity(keys=[...])` (oder einen eigenen Codec), damit jede Instanz verifizieren kann, was eine Schwesterinstanz ausgestellt hat. Das Siegel bindet jedes Token an ein Zeitfenster, den auslösenden Request und den authentifizierten Principal, wenn der Request eine vom SDK validierte Authentifizierung trägt oder `bind_principal=` dein eigenes Identitätssignal liefert (**[`requestState` schützen](#protecting-requeststate)**).

Das ist der Mechanismus, der serverinitiiertes Sampling und den Rest des Push-artigen Rückkanals ersetzt; siehe **[Veraltete Features](../deprecated.md)**.
