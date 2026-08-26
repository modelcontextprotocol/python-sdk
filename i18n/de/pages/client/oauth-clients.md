---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth-Clients {#oauth-clients}

Manche MCP-Server sind geschützt. Schickst du ihnen einen Request ohne Token, antworten sie mit `401 Unauthorized`.

Mit **`OAuthClientProvider`** bekommst du das Token. Das ist überhaupt kein MCP-Objekt. Es ist ein `httpx2.Auth`, der Standard-Hook von httpx2 für „tu etwas mit jedem Request“. Du hängst ihn an einen `httpx2.AsyncClient`, übergibst diesen Client dem Streamable-HTTP-Transport und denkst nicht mehr darüber nach.

Diese Seite ist die Client-Seite. Wie dein eigener Server ein Token verlangt, steht in **[Autorisierung](../run/authorization.md)**.

## Der Provider {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

Du gibst ihm vier Dinge:

* `server_url`: der MCP-Endpunkt, mit dem du dich verbindest. Alles Weitere findet der Provider von dort aus selbst heraus.
* `client_metadata`: das, was du in das Formular „Anwendung registrieren“ eines Autorisierungsservers eintragen würdest.
* `storage`: wo Tokens zwischen den Läufen liegen.
* `redirect_handler` und `callback_handler`: die beiden Momente, in denen ein Mensch beteiligt ist.

Sonst erwähnt nichts in der Datei OAuth. `main()` sieht nie ein Token.

### Client-Metadaten {#client-metadata}

`OAuthClientMetadata` ist das echte Registrierungsdokument aus [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591), als Pydantic-Modell.

Du setzt drei Felder. Die Standardwerte füllen den Rest: `grant_types` ist bereits `["authorization_code", "refresh_token"]` und `response_types` ist bereits `["code"]` – genau der Flow, den dieser Provider ausführt.

!!! check
    Weil es ein Pydantic-Modell ist, validiert es, **bevor ein einziges Byte über das Netzwerk geht**.
    Lass `redirect_uris` weg, und die Konstruktion scheitert sofort mit einem `ValidationError`, der
    das Feld benennt:

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    Kein Browser geöffnet, keine halbfertige Registrierung auf dem Autorisierungsserver zurückgelassen.

### Token-Speicherung {#token-storage}

**`TokenStorage`** ist ein `Protocol` mit vier async-Methoden. Du erbst von nichts; schreib die Methoden, und jede beliebige Klasse ist ein Token-Speicher:

* `get_tokens` / `set_tokens` halten das `OAuthToken`: Access-Token, Refresh-Token, Ablaufzeit, Scope.
* `get_client_info` / `set_client_info` halten die `OAuthClientInformationFull`, die der Autorisierungsserver ausgestellt hat, als der Provider dich registrierte – einschließlich deiner `client_id`.

Die In-Memory-Variante oben funktioniert. Sie vergisst aber auch alles, wenn der Prozess endet, sodass der nächste Lauf das ganze Prozedere noch einmal durchläuft. Speichere sie in einer Datei oder im Schlüsselbund deiner Plattform, und der nächste Lauf bleibt stumm.

!!! tip
    Speichere `client_info`, nicht nur die Tokens. Der Provider registriert sich dynamisch, wenn er
    beim ersten Mal keine gespeicherte `client_info` findet. Wirfst du sie weg, erzeugst du bei jedem Lauf eine neue Registrierung.

### Die zwei Handler {#the-two-handlers}

Der Authorization-Code-Flow braucht genau einmal einen Menschen: Jemand muss sich anmelden und auf „Zulassen“ klicken.

* **`redirect_handler`** wird mit der fertig gebauten Autorisierungs-URL awaited. `client_id`, `redirect_uri`, `state` und die PKCE-Challenge stecken bereits darin. Deine einzige Aufgabe ist, einen Browser dorthin zu bringen. Eine Desktop-App ruft `webbrowser.open` auf; diese Datei gibt sie aus.
* **`callback_handler`** wird als Nächstes awaited. Er wartet, bis die Person wieder auf deiner `redirect_uri` landet, und gibt die Query-Parameter dieses Redirects als `AuthorizationCodeResult` zurück.

Ein echter Client betreibt auf der Redirect-URI einen kleinen lokalen HTTP-Server, statt `input()` aufzurufen. Die Form ist identisch: weitergeleitet werden, `code`, `state` und `iss` zurückgeben.

!!! warning
    Reiche `state` und `iss` genau so durch, wie sie angekommen sind. Der Provider vergleicht `state` mit dem Wert,
    den er generiert hat, und `iss` mit dem Issuer, den er ermittelt hat, und lehnt eine Abweichung ab. Sie sind die
    Schutzmaßnahmen gegen CSRF und Server-Verwechslung.

### In den `Client` {#into-the-client}

Sieh dir `main()` an. Der Provider kommt an den **httpx2-Client**, der httpx2-Client kommt in `streamable_http_client(url, http_client=...)`, und dieser Transport kommt in `Client`.

`streamable_http_client` hat kein Keyword `auth=`. Alles auf HTTP-Ebene (Auth, Header, Timeouts, Proxys) gehört auf den `httpx2.AsyncClient`, den du mitbringst. Diese Schichtung steht in **[Client-Transporte](transports.md)**.

## Was der Provider für dich tut {#what-the-provider-does-for-you}

Wenn `Client` zum ersten Mal einen Request schickt, antwortet der Server mit `401`. Der Provider übernimmt:

1. **Discovery.** Er liest den `WWW-Authenticate`-Header, holt die Protected Resource Metadata des Servers von `/.well-known/oauth-protected-resource`, erfährt, welcher Autorisierungsserver diese Ressource schützt, und holt die Metadaten *dieses* Servers.
2. **Registrierung.** Nichts im Speicher? Er registriert dich dynamisch mit deiner `OAuthClientMetadata` und speichert das Ergebnis.
3. **Autorisierung.** Er generiert das PKCE-Paar und einen `state`, baut die Autorisierungs-URL, awaited deinen `redirect_handler` und awaited dann deinen `callback_handler` für den Code.
4. **Austausch.** Er tauscht den Code gegen ein `OAuthToken`, speichert es und wiederholt deinen ursprünglichen Request mit `Authorization: Bearer ...`.

Danach ist Ruhe. Tokens kommen aus dem Speicher, ein abgelaufenes Access-Token wird mit dem Refresh-Token erneuert, und erst wenn nichts davon klappt, führt er den Flow erneut aus.

Nichts davon hast du geschrieben. Zwei Keyword-Argumente bleiben übrig (`client_metadata_url` und `validate_resource_url`), und diese Datei braucht keines davon. `client_metadata_url` ist dasjenige, das man kennen sollte; es bekommt unten einen eigenen Abschnitt.

### Ausprobieren {#try-it}

Die meisten Beispiele in dieser Dokumentation kannst du mit einem In-Memory-`Client(server)` prüfen. Dieses nicht: Der ganze Sinn des Flows ist ein HTTP-`401`, und zwischen einem In-Memory-Client und seinem Server gibt es kein HTTP.

Das Repository liefert die Live-Variante mit. `examples/servers/simple-auth/` betreibt einen eigenständigen Autorisierungsserver und einen geschützten MCP-Server; `examples/clients/simple-auth-client/` ist der Client dieser Seite, ausgebaut zu einem kleinen CLI. Sein README enthält die beiden Befehle: Starte die Server, lass den Client gegen sie laufen, und du siehst die vier Schritte vorbeiziehen.

## Client ID Metadata Documents {#client-id-metadata-documents}

Die Revision 2026-07-28 der Spezifikation erklärt die dynamische Client-Registrierung für veraltet, zugunsten von **Client ID Metadata Documents** (CIMD). Statt jedem Autorisierungsserver, dem er begegnet, per POST eine frische Registrierung zu schicken, veröffentlicht dein Client ein einziges JSON-Dokument über sich selbst unter einer stabilen HTTPS-URL, und diese URL *ist* seine `client_id`. Der Autorisierungsserver holt das Dokument; der Provider fasst es nie an.

Das SDK spricht es bereits: Übergib die URL als `client_metadata_url=`, wenn du den Provider erzeugst. Wenn die Metadaten des Autorisierungsservers `client_id_metadata_document_supported: true` ankündigen, überspringt der Provider den `/register`-Request komplett: Die URL geht als `client_id` in den Flow, und es gibt kein `client_secret`. Wenn der Server es nicht ankündigt (die meisten tun das noch nicht) oder du nie eine URL übergibst, fällt der Provider **stillschweigend** auf die dynamische Registrierung zurück, und alles oben funktioniert genau wie beschrieben. Eine gespeicherte `client_info` hat weiterhin Vorrang vor beidem.

Die URL muss HTTPS sein und einen Pfad haben, der nicht das Wurzelverzeichnis ist; alles andere ist ein `ValueError` bei der Konstruktion, bevor irgendein Netzwerkverkehr stattfindet. Das mitgelieferte `examples/clients/simple-auth-client/` nimmt sie als Umgebungsvariable `MCP_CLIENT_METADATA_URL` entgegen.

## Maschine zu Maschine {#machine-to-machine}

Ein nächtlicher Job, ein CI-Schritt, ein anderer Dienst. Es gibt keinen Browser und niemanden, der auf „Zulassen“ klickt. Das ist der **Client-Credentials**-Grant: Du besitzt bereits eine `client_id` und ein `client_secret`, und der Token-Endpunkt ist der ganze Flow.

`ClientCredentialsOAuthProvider` ist dasselbe `httpx2.Auth`, ohne den Menschen:

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

Was sich geändert hat:

* Keine `OAuthClientMetadata`, keine Handler. Du übergibst `client_id` und `client_secret`; der Provider baut eine minimale `client_credentials`-Registrierung darum herum und überspringt die dynamische Registrierung komplett.
* `scope` ist ein durch Leerzeichen getrennter String, das OAuth-Format auf der Leitung.
* Alles danach ist identisch: dasselbe `TokenStorage`, derselbe `httpx2.AsyncClient(auth=...)`, derselbe `streamable_http_client`.

Standardmäßig reist das Secret als HTTP Basic Auth im Token-Request (`client_secret_basic`). Übergib `token_endpoint_auth_method="client_secret_post"`, um es stattdessen in den Formular-Body zu legen. Manche Autorisierungsserver akzeptieren nur eine der beiden Varianten.

!!! tip
    Lies `client_secret` aus der Umgebung oder einem Secret-Manager, nie aus der Versionsverwaltung.

!!! info
    Ein weiterer Provider liegt in `mcp.client.auth.extensions.client_credentials`:
    **`PrivateKeyJWTOAuthProvider`**, für Clients, die sich mit einem JWT statt einem
    gemeinsamen Secret authentifizieren (`private_key_jwt`, die Variante mit Schlüsselpaar und Workload-Identität). Er folgt
    demselben Muster: einen erzeugen, auf `auth=` setzen. Dasselbe Modul liefert
    `SignedJWTParameters` und `static_assertion_provider`, zwei Helfer, die seine Assertion bauen.

Es gibt noch eine Situation ohne Menschen: Der Client gehört zu einem Unternehmen, dessen Identity Provider – nicht die Person am Host – entscheidet, welche MCP-Server er erreichen darf. Das ist ein anderer Grant mit eigenem Vertrauensmodell und eigener Seite: **[Identity Assertion](identity-assertion.md)**.

## Wenn es fehlschlägt {#when-it-fails}

Wenn der OAuth-Flow schiefgeht, löst der Provider einen `OAuthFlowError` aus `mcp.client.auth` aus. Er hat zwei Unterklassen. `OAuthRegistrationError` bedeutet, dass die Registrierung keinen Client ergeben hat, den du verwenden kannst: Der Autorisierungsserver hat die Registrierung abgelehnt, oder er hat dich zwar registriert, aber mit Zugangsdaten, die dieser Flow nicht verwenden kann (zum Beispiel eine Authentifizierungsmethode, die er nicht implementiert). `OAuthTokenError` bedeutet, dass kein Token beschafft werden konnte: Der Token-Endpunkt hat abgelehnt, oder ein gespeicherter Client-Eintrag trägt eine Authentifizierungsmethode, die dieser Client nicht anwenden kann – das wird beim Bauen des Token-Requests gemeldet statt gesendet. Ein einziges `except OAuthFlowError:` deckt Discovery, Registrierung, Autorisierung und Austausch ab.

Nicht alles ist ein Flow-Fehler. Das Netzwerk kann weiterhin ausfallen; das sind gewöhnliche `httpx2`-Exceptions, und sie werden unverändert durchgereicht.

## Zusammenfassung {#recap}

* `OAuthClientProvider` ist ein `httpx2.Auth`. Setze ihn auf einen `httpx2.AsyncClient`, übergib diesen an `streamable_http_client(url, http_client=...)`, und `Client` erfährt nie, dass OAuth stattgefunden hat.
* Du lieferst vier Dinge: die Server-URL, eine `OAuthClientMetadata`, ein `TokenStorage` und das Paar aus Redirect- und Callback-Handler.
* `TokenStorage` ist ein `Protocol`: vier async-Methoden, keine Basisklasse. Speichere `client_info` ebenso dauerhaft wie die Tokens.
* Discovery, Registrierung (dynamisch oder über ein **Client ID Metadata Document**), PKCE, die Prüfungen von `state` und `iss` sowie die Token-Erneuerung sind Aufgabe des Providers, nicht deine.
* `ClientCredentialsOAuthProvider` ist die Variante ohne Menschen: `client_id` + `client_secret`, keine Handler, kein Browser.
* Jeder OAuth-Fehlschlag ist ein `OAuthFlowError`; `OAuthRegistrationError` und `OAuthTokenError` sind seine Unterklassen.

Die andere Hälfte dieses Handshakes – wie dein *Server* das Token verlangt – steht in **[Autorisierung](../run/authorization.md)**.
