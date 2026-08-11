---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# Identity Assertion {#identity-assertion}

Ein gewöhnlicher OAuth-Provider (**[OAuth-Clients](oauth-clients.md)**) stellt dem MCP-Server zuerst eine Frage: *Welchem Autorisierungsserver vertraust du?* Er folgt der Antwort, wohin sie auch zeigt, und dann meldet sich entweder eine Person an oder ein vorab geteiltes Secret tritt an ihre Stelle.

Ein Unternehmen will weder das eine noch das andere pro Server entschieden haben. Es betreibt längst einen Identity Provider (Okta, Microsoft Entra ID, einen eigenen); die Person hat sich dort heute Morgen schon angemeldet; und es ist der eine Ort, an dem das Security-Team entscheiden will, wer was erreichen darf. [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), die Erweiterung **Enterprise-Managed Authorization**, verlegt die Entscheidung dorthin. Der IdP signiert ein kurzlebiges JWT, einen **Identity Assertion JWT Authorization Grant**, den **ID-JAG**: die Aussage, dass *diese Person* über *diesen Client* *diesen MCP-Server* erreichen darf. Der Client tauscht ihn gegen ein gewöhnliches Access Token. Kein Browser, kein Zustimmungsdialog, keine dynamische Registrierung.

Diese Seite zeigt beide Seiten dieses Tauschs. Der MCP-Server selbst ändert sich nie: Er ist nach wie vor der Ressourcenserver aus **[Autorisierung](../run/authorization.md)** und prüft jedes Token, das ankommt.

## Zwei Token-Requests {#two-token-requests}

Zwei verschiedene Instanzen sind im Spiel, und sie auseinanderzuhalten ist schon fast das ganze Verständnis dieser Seite. Der **Unternehmens-IdP** ist der Identity Provider deiner Organisation: Er kennt die Identität der Beschäftigten, bei ihm liegen die Richtlinien, und er stellt den ID-JAG aus. Das SDK spricht nie mit ihm. Der **MCP-Autorisierungsserver** ist dieselbe Partei wie in **[Autorisierung](../run/authorization.md)**: der Issuer, den die Metadaten des MCP-Servers nennen, die Stelle, die die Tokens ausstellt, die dieser MCP-Server akzeptiert. In einem gewöhnlichen OAuth-Flow sind diese beiden Rollen meist ein und dasselbe System. Hier sind es zwei, und der ganze Grant besteht darin, dass der zweite zustimmt, dem ersten zu vertrauen.

Der Client stellt an jeden der beiden genau einen Token-Request.

1. **An den Unternehmens-IdP.** Der Client tauscht die Anmeldung der Person (ihr OpenID-Connect-ID-Token) gegen den ID-JAG. Das ist ein Token Exchange nach [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693), er läuft vollständig über die API deines IdP, und **das SDK führt ihn nicht aus**. Das machst du, in einem einzigen asynchronen Callback. Hier fällt auch die Richtlinienentscheidung: Ein IdP, der Nein sagt, stellt den ID-JAG gar nicht erst aus, und es gibt nichts vorzulegen.
2. **An den MCP-Autorisierungsserver.** Der Client legt den ID-JAG im `jwt-bearer`-Grant nach [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) vor (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, der ID-JAG als `assertion`) und erhält das Access Token. **Diesen Request stellt das SDK**, und ihn anzunehmen ist das Einzige, was diese Seite einem Autorisierungsserver hinzufügt.

Alles Weitere dreht sich um den zweiten Request: den Client, der ihn sendet, und den Autorisierungsserver, der ihn beantwortet.

## Der Client {#the-client}

**`IdentityAssertionOAuthProvider`** liegt in `mcp.client.auth.extensions.identity_assertion`. Wie jeder Provider in **[OAuth-Clients](oauth-clients.md)** ist er ein `httpx2.Auth`: Erzeuge einen, setze ihn auf `auth=` und übergib den `httpx2.AsyncClient` an den Transport.

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

Lies die Datei von unten nach oben.

* `main()` ist das übliche `main()` eines OAuth-Clients (**[OAuth-Clients](oauth-clients.md)**), Zeile für Zeile unverändert. Genau darum geht es: Sobald der Provider existiert, weiß nichts dahinter, welcher Grant das Token erzeugt hat.
* Der Provider nimmt entgegen, was die anderen Provider nicht per Discovery herausfinden können: eine `client_id` und ein `client_secret`, die jemand beim Autorisierungsserver **vorab registriert** hat, den `issuer` dieses Autorisierungsservers und `assertion_provider`, einen asynchronen Callback, der auf Anforderung einen frischen ID-JAG liefert.
* `storage` ist dasselbe `TokenStorage`-Protokoll. Aufgerufen werden nur die beiden Token-Methoden; dynamische Registrierung gibt es hier nicht, also auch kein `client_info`, das man sich merken müsste.

### Der Assertion-Provider {#the-assertion-provider}

`fetch_id_jag(audience, resource)` ist der einzige Code, den du schreibst. Er wird einmal pro Token-Austausch aufgerufen, nie beim Konstruieren, und erst *nachdem* die Metadaten des Autorisierungsservers abgerufen und validiert wurden – so gibt ein falsch konfigurierter Issuer nie eine Assertion preis. Seine beiden Argumente sind zwei der Claims, mit denen der ID-JAG ausgestellt werden muss: `audience` ist der Issuer des Autorisierungsservers (das `aud` des ID-JAG) und `resource` der kanonische Bezeichner des MCP-Servers (das `resource` des ID-JAG). Den dritten hast du bereits: Der `client_id`-Claim des ID-JAG muss die `client_id` nennen, die du dem Provider gegeben hast, sonst verweigert der Autorisierungsserver den Austausch.

`idp_issue_id_jag` darüber ist **nicht dein Code**. Die Funktion steht stellvertretend für den Identity Provider und signiert die Assertion im selben Prozess, damit die Datei vollständig ist und du jeden Claim lesen kannst, den ein ID-JAG trägt. Ein echtes `fetch_id_jag` stellt stattdessen den ersten Token-Request aus dem vorigen Abschnitt: einen Token Exchange nach [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) gegen deinen IdP, definiert im Draft zum Identity Assertion JWT Authorization Grant, den [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) profiliert. Das ID-Token der angemeldeten Person geht als `subject_token` hinein, der `requested_token_type` ist der eigene URN des ID-JAG (`urn:ietf:params:oauth:token-type:id-jag`), `audience` und `resource` werden unverändert durchgereicht, und die Response enthält den ID-JAG. Nach genau diesem Austausch unter genau diesen Namen suchst du in der Dokumentation deines IdP.

!!! tip
    Für jeden Austausch wird ein frischer ID-JAG angefordert, und genau das ist der Sinn: Er ist ein
    Grant zur einmaligen Verwendung, der nur Minuten lebt, und der Autorisierungsserver auf dieser Seite
    nimmt denselben kein zweites Mal an. Cache ihn nicht. Wiederverwendet wird das Access Token, das du
    dafür bekommst.

### Der Issuer ist Konfiguration {#the-issuer-is-configuration}

Hier liegt die Umkehrung. `OAuthClientProvider` fragt den Ressourcenserver, welchen Autorisierungsserver er verwenden soll, und folgt der Antwort, wohin sie auch zeigt. Dieser Provider weigert sich: `issuer` ist erforderlich, die Metadaten nach [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) werden vom eigenen Well-known-Pfad dieses Issuers abgerufen, der Token-Endpunkt muss auf dem Origin dieses Issuers liegen, und der Ressourcenserver wird nie irgendetwas gefragt.

Die Erweiterung verlangt das nicht; es ist eine bewusst strengere Entscheidung. Dieser Client trägt zwei Dinge mit sich, die sich zu stehlen lohnen – ein vorab registriertes Secret und eine an eine Audience gebundene Assertion –, und ein Client, der sich von einem kompromittierten MCP-Server zu einem von Angreifenden kontrollierten Autorisierungsserver lenken ließe, würde beides dorthin posten. Den Issuer beim Konstruieren festzulegen, streicht dieses Gespräch komplett.

!!! warning
    Der konfigurierte `issuer` wird mit dem Feld `issuer` des Metadatendokuments per einfachem
    String-Vergleich nach RFC 8414 §3.3 verglichen: Zeichen für Zeichen, abschließender Schrägstrich
    inklusive, ohne Normalisierung. Rate ihn nicht. Rufe `/.well-known/oauth-authorization-server` von
    deinem Autorisierungsserver ab und kopiere den `issuer`-Wert, den er zurückgibt. Für den
    Autorisierungsserver auf dieser Seite ist das `https://auth.example.com/`, mit dem Schrägstrich, weil
    sein Issuer aus einem Pydantic-URL-Objekt gebaut wurde. Eine Abweichung stoppt den Flow bei
    `OAuthFlowError: Authorization server metadata issuer
    mismatch`, bevor auch nur ein einziges Credential oder eine Assertion gesendet wird.

### Ein vertraulicher Client {#a-confidential-client}

`client_secret` ist erforderlich; ohne löst der Konstruktor einen `ValueError` aus. Das IETF-Profil unter [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) reserviert diesen Grant für vertrauliche Clients, SEP-990 verlangt, dass sich der Client authentifiziert, und dieses SDK setzt beides durch, indem es auf einem geteilten Secret besteht. `token_endpoint_auth_method` legt fest, wo es mitreist: `client_secret_post` (der Standardwert, im Formular-Body) oder `client_secret_basic` (ein HTTP-Basic-Header). Das Profil erlaubt außerdem `private_key_jwt`; dieser Provider unterstützt es nicht.

!!! tip
    Lies `client_secret` aus der Umgebung oder einem Secret-Manager, nie aus der Versionsverwaltung.

### Was der Provider für dich erledigt {#what-the-provider-does-for-you}

Der erste Request geht unauthentifiziert raus, und das `401` des Servers startet den Flow.

1. **Discovery.** Er ruft die Metadaten des Autorisierungsservers vom Well-known-Pfad nach [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) des konfigurierten Issuers ab, prüft, dass der `issuer` des Dokuments übereinstimmt, und prüft, dass der Token-Endpunkt auf dem Origin des Issuers liegt.
2. **Die Assertion.** Er ruft deinen `assertion_provider` auf und wartet auf das Ergebnis.
3. **Austausch.** Er sendet den `jwt-bearer`-Grant per POST an den Token-Endpunkt, speichert das `OAuthToken` und wiederholt deinen ursprünglichen Request mit `Authorization: Bearer ...`.

Ein `403`, dessen `WWW-Authenticate` `insufficient_scope` nennt, führt die Schritte 2 und 3 erneut aus, mit der Vereinigung aus deinem `scope` und dem in der Challenge geforderten. (`scope` ist immer nur eine Bitte; der Autorisierungsserver dieser Seite gewährt, was der ID-JAG sagt, und nichts sonst.) Ein Refresh Token gibt es hier nirgends: Läuft das Access Token ab, lässt das nächste `401` einen frischen ID-JAG ausstellen und tauscht erneut, und *das* ist der Hebel, den der IdP in der Hand hält. Fehler sind dieselben zwei Exceptions wie überall in **[OAuth-Clients](oauth-clients.md)**: `OAuthFlowError` für Discovery und Validierung, ihre Unterklasse `OAuthTokenError`, wenn der Token-Endpunkt Nein sagt.

## Der Autorisierungsserver {#the-authorization-server}

Meistens hörst du hier auf. Der MCP-Autorisierungsserver ist das Produkt von jemand anderem, ID-JAGs anzunehmen ist eine Einstellung in dessen Konfiguration, die du einschaltest, und die SDK-Hälfte von [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) ist der Client oben.

Das SDK kann aber auch selbst der Autorisierungsserver *sein*: `create_auth_routes` gibt die Routen des Autorisierungsservers als Liste zurück, die jede Starlette-App mounten kann – so betreibt `examples/servers/simple-auth/` im Repository einen. SEP-990 fügt dieser Oberfläche ein Flag und eine Methode hinzu:

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` schaltet alles frei. Ausgeschaltet – das ist der Standardwert – beantwortet `/token` diesen Grant mit `unsupported_grant_type`, selbst wenn du den Hook implementiert hast, und die Metadaten erwähnen ihn nicht. Eingeschaltet erhalten die Metadaten den Grant-Typ `jwt-bearer` und listen `urn:ietf:params:oauth:grant-profile:id-jag` in `authorization_grant_profiles_supported`, dem Feld, mit dem die Erweiterung Unterstützung bekannt gibt. (Der Client dieses SDK liest es nie: Er ist für genau einen Issuer eingerichtet und fragt einfach.)
* **`exchange_identity_assertion`** ist der Hook. Bevor er läuft, hat das SDK den Client authentifiziert, öffentliche Clients abgewiesen und Clients abgewiesen, deren Registrierung den Grant nicht aufführt. Du bekommst ein `IdentityAssertionParams` (die rohe `assertion`, die angeforderten `scopes` und `resource`) und gibst ein schlichtes `OAuthToken` zurück.
* Die dynamische Client-Registrierung lehnt diesen Grant ausnahmslos ab, deshalb bedient `get_client` hier einen von Hand eingerichteten Client. Ein ID-JAG-Client kann sich nicht selbst ins Leben registrieren.
* Die halbe Klasse besteht aus Ablehnungen. `OAuthAuthorizationServerProvider` ist der *ganze* Autorisierungsserver, also verlangt er auch den Authorization-Code-Flow; ein Server, der Personen zusätzlich anmeldet, implementiert diese Methoden wirklich, und dieser hier hat genau eine Tür.

!!! warning
    Das SDK dekodiert die Assertion nie: Nur dein Deployment weiß, welchem IdP es vertraut und welche
    Schlüssel dieser IdP veröffentlicht, deshalb ist alles innerhalb von `exchange_identity_assertion`
    tragend. Prüfe die Signatur gegen die veröffentlichten Schlüssel des IdP (sein JWKS; das geteilte
    Secret hier gehört zur Demo) sowie `iss` und `exp`, gemäß [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3. Verlange, dass `typ`
    im JWT-Header `oauth-id-jag+jwt` ist – der Schutz des Profils dagegen, dass irgendein anderes JWT
    als Grant wiedereingespielt wird. Verlange, dass `aud` dein eigener Issuer ist. Verlange, dass der
    `client_id`-Claim des ID-JAG dem Client entspricht, den der Handler authentifiziert hat, und dass
    sein `resource`-Claim eine Ressource nennt, die du tatsächlich bedienst. Merke dir `jti` bis zum
    `exp` der Assertion, damit sie nur einmal akzeptiert wird. Und entnimm die gewährten Scopes und vor
    allem das `resource` des ausgestellten Tokens dem validierten ID-JAG, nie dem Request:
    `params.resource` ist, was immer der Client eingetippt hat. Die vollständigen Verarbeitungsregeln
    stehen in der [Spezifikation zu Enterprise-Managed Authorization](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization).

Eine fehlerhafte Assertion weist du mit `TokenError("invalid_grant", ...)` ab. Der andere Fehlercode in diesem Flow ist `invalid_target`: Ein ID-JAG, der eine Ressource nennt, die du nicht bedienst, wird damit abgelehnt – das verhindert, dass dieser Server Tokens für die Ressource von jemand anderem ausstellt. Und die gewährten Scopes stammen aus dem `scope`-Claim des ID-JAG (eine Assertion ohne ihn wird ebenfalls abgelehnt); deiner könnte stattdessen die Gruppen der Person abbilden.

Und beachte, was das zurückgegebene `OAuthToken` nicht enthält: ein Refresh Token. Der IdP entscheidet, wie lange diese Person Zugang behält, indem er entscheidet, ob er den nächsten ID-JAG ausstellt. Ein hier ausgestelltes Refresh Token gäbe diese Entscheidung stillschweigend wieder ab.

!!! info
    Ein Server, der seinen Autorisierungsserver noch mit `auth_server_provider=` einbettet, erreicht
    denselben Code über `AuthSettings(identity_assertion_enabled=True)`. **[Autorisierung](../run/authorization.md)** erklärt,
    warum neue Server nicht dort anfangen sollten.

!!! check
    Verbinde die beiden Dateien dieser Seite miteinander, und der ganze Grant ist ein einziges `POST /token`:

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    Kein `/authorize`, kein `/register`, kein Abruf der Protected-Resource-Metadaten. Die einzigen
    Requests auf der Leitung sind der, der das `401` ausgelöst hat, der Well-known-Abruf, dieser
    Austausch und danach gewöhnlicher MCP-Verkehr mit angehängtem Bearer-Token. Und das `sub`, das dein
    Validator aus dem ID-JAG gelesen hat, ist genau das, was `get_access_token().subject` innerhalb
    eines Tools meldet.

### Ausprobieren {#try-it}

`examples/stories/identity_assertion/` im SDK-Repository ist diese Seite in echt: derselbe `exchange_identity_assertion`-Validator, ein MCP-Server, der durch dessen Tokens abgesichert ist, ein Stellvertreter-IdP und der Client, in einem einzigen Programm, das sich selbst prüft. `uv run python -m stories.identity_assertion.client --http` führt den ganzen Austausch aus und prüft, dass die Person, die der IdP benannt hat, dieselbe ist, die das Tool sieht.

## Zusammenfassung {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) lässt den Identity Provider des Unternehmens – nicht die Person am Host – entscheiden, welche MCP-Server ein Client erreichen darf. Der IdP signiert diese Entscheidung in einen **ID-JAG**.
* Den ID-JAG zu beschaffen ist ein Token Exchange nach [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) gegen *deinen IdP*, und das SDK führt ihn nicht aus. Ihn dem MCP-Autorisierungsserver vorzulegen ist der `jwt-bearer`-Grant nach [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523), und davon übernimmt das SDK beide Seiten.
* `IdentityAssertionOAuthProvider` ist ein weiteres `httpx2.Auth`: ein vorab registrierter vertraulicher Client, ein festgelegter `issuer` und ein einziger Callback `assertion_provider(audience, resource)`. Kein Browser, keine Registrierung, kein Refresh Token.
* Der Autorisierungsserver wird nie über den Ressourcenserver entdeckt. Setze `issuer` auf genau den String, den sein Metadatendokument ausliefert; verglichen wird Zeichen für Zeichen.
* Serverseitig: `identity_assertion_enabled=True` plus `exchange_identity_assertion`. Das SDK authentifiziert den Client und schaltet den Grant frei; den ID-JAG zu validieren ist ganz deine Sache, und das ausgestellte Token ist an das `resource` des ID-JAG gebunden, nicht an das des Requests.

Die eine Partei, die diese Seite nie angefasst hat, ist der MCP-Server. Was er mit dem Token macht, das du gerade ausgestellt hast, hat er schon in **[Autorisierung](../run/authorization.md)** getan.
