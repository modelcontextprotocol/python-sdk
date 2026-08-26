---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# Autorisierung {#authorization}

Über Streamable HTTP ist dein MCP-Server ein ganz gewöhnlicher Webdienst, und du schützt ihn so, wie du jeden Webdienst schützt: mit OAuth-2.1-Bearer-Tokens.

In der Sprache von OAuth ist dein Server ein **Resource Server**. Er meldet nie jemanden an und stellt nie ein Token aus. Er tut genau eine Sache: Er sieht sich bei jedem Request den `Authorization`-Header an und entscheidet, ob das Token darin gültig ist.

Diese Seite behandelt die Server-Seite. Ein Client, der deinen Authorization Server findet und das Token holt, steht unter **[OAuth-Clients](../client/oauth-clients.md)**.

## Die drei Beteiligten {#the-three-parties}

* Der **Authorization Server** meldet Personen an und stellt Access Tokens aus. Den schreibst du nicht. Das ist dein Identity Provider (Auth0, Keycloak, Entra, dein eigener).
* Der **Resource Server** ist dein MCP-Server. Er prüft das Token bei jedem Request.
* Der **Client** findet heraus, welchem Authorization Server du vertraust, holt sich dort ein Token und schickt es dir als `Authorization: Bearer <token>` zurück.

Das ist das ganze Dreieck. Alles auf dieser Seite betrifft den mittleren Punkt.

## Ein Token-Verifier {#a-token-verifier}

Das SDK hat keine Meinung dazu, wie ein gültiges Token aussieht. Das sagst du ihm, indem du **`TokenVerifier`** implementierst:

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` ist ein Protokoll mit einer einzigen asynchronen Methode. `verify_token` bekommt das rohe Token aus dem `Authorization`-Header und gibt ein **`AccessToken`** zurück, wenn es gültig ist, und `None`, wenn nicht. Mehr gibt es nicht zu implementieren.
* Dieser hier schlägt das Token in einer Tabelle nach. Ein echter prüft eine JWT-Signatur oder ruft den Token-Introspection-Endpunkt des Authorization Servers auf. Dieser Code gehört dir; das SDK ruft ihn nur auf.
* `token_verifier=` und `auth=` treten immer gemeinsam auf. Übergibst du das eine ohne das andere, löst `MCPServer(...)` einen `ValueError` aus, bevor auch nur ein Request bedient wird.

`AuthSettings` ist das öffentliche Gesicht deines Resource Servers:

* `issuer_url`: der Authorization Server, der deine Tokens ausstellt.
* `resource_server_url`: die öffentliche URL dieses MCP-Endpunkts. Sie benennt, für *welche* Ressource ein Token gilt, und unter ihr liegt das Discovery-Dokument.
* `required_scopes`: jedes Token muss alle davon tragen.

!!! tip
    `examples/servers/simple-auth/` im SDK-Repository enthält einen `IntrospectionTokenVerifier`, der den
    [RFC-7662](https://datatracker.ietf.org/doc/html/rfc7662)-Endpunkt eines echten Authorization Servers aufruft. Diese Form haben die meisten Verifier in Produktion.

## Was du über HTTP bekommst {#what-you-get-over-http}

Autorisierung lebt in HTTP-Headern, es gibt sie also nur auf den HTTP-Transporten. Betreibe sie auf dem, den du bereitstellst: `mcp.run(transport="streamable-http")` legt sie auf `http://127.0.0.1:8000/mcp`, und alles Weitere steht in **[Den Server betreiben](index.md)**. Die App hat jetzt zwei Routen:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

Du hast ein Tool registriert. Die zweite Route stammt vom SDK.

### Discovery {#discovery}

Schick ein `GET` an diesen Well-Known-Pfad, und du bekommst **Protected Resource Metadata nach [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)**, direkt aus deinen `AuthSettings` gebaut:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

Über dieses Dokument findet ein Client, der noch nie von deinem Server gehört hat, den Weg hinein: Er liest `authorization_servers` und holt sich dort ein Token. Nichts davon hast du geschrieben.

!!! check
    Ruf `/mcp` ohne Token auf (oder mit einem, für das dein Verifier `None` zurückgegeben hat), und der Request wird
    an der Tür abgewiesen:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    Nichts wurde geparst, kein Tool ist gelaufen. Und der `resource_metadata`-Verweis in `WWW-Authenticate`
    macht Discovery automatisch: 401 -> Metadaten-Dokument -> Authorization Server -> Token -> erneuter Versuch.

!!! warning
    Nichts davon schützt `stdio`. Eine Pipe hat keinen `Authorization`-Header, also wird `token_verifier` dort nie
    befragt. Die Sicherheitsgrenze eines `stdio`-Servers ist der Prozess, der ihn gestartet hat. Dasselbe
    gilt für den In-Memory-`Client(mcp)`, den du in Tests verwendest: Er verbindet sich direkt mit dem Server-Objekt
    und überspringt die HTTP-Schicht, Autorisierung eingeschlossen.

## Die Identität des Aufrufers {#the-callers-identity}

In jedem Handler ist **`get_access_token()`** das `AccessToken`, das dein Verifier für den aktuellen Request zurückgegeben hat:

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* Es funktioniert in Tools, Ressourcen und Prompts, und du musst nichts herumreichen: Die Auth-Middleware speichert es pro Request in einer Context-Variablen.
* Du bekommst **dasselbe Objekt zurück, das dein Verifier gebaut hat**: `client_id`, `scopes`, `subject`, `expires_at` und alle zusätzlichen `claims`, die du angehängt hast. Das ist der Ansatzpunkt für Regeln pro Tool: Lies die Scopes und lehne ab.
* Außerhalb eines authentifizierten HTTP-Requests gibt es `None` zurück. In-Memory und über `stdio` ist es immer `None`.

Ruf `whoami` mit `Authorization: Bearer alice-token` auf, und das Modell liest:

```text
alice (scopes: notes:read)
```

## Die Hälfte, die das SDK nicht übernimmt {#the-half-the-sdk-doesnt-do}

Das SDK gibt dir die Resource-Server-Hälfte: prüfen, bekanntmachen, ablehnen. Es gibt dir keine Login-Seite, keinen Consent-Screen und kein Token.

Um alle drei Beteiligten in Bewegung zu sehen, starte `examples/servers/simple-auth/` aus dem SDK-Repository (ein kleiner Authorization Server und ein Resource Server, genau wie auf dieser Seite eingerichtet) und richte dann `examples/clients/simple-auth-client/` darauf, um den kompletten Ablauf aus Discovery und Token-Abruf zu sehen.

!!! info
    Es gibt ein zweites Konstruktor-Argument, `auth_server_provider=`, das einen vollständigen Authorization
    Server in deinen MCP-Server einbettet. Es stammt aus der Zeit vor der AS/RS-Trennung, um die herum die
    MCP-Autorisierungsspezifikation gebaut ist. Neue Server sollten nicht danach greifen.

Ein Authorization Server kann statt einer Person, die sich durch einen Consent-Screen klickt, auch die signierte Assertion eines Unternehmens-Identity-Providers akzeptieren, und das SDK unterstützt beide Seiten dieses Austauschs. Der Grant und der Client, der ihn vorlegt, stehen unter **[Identity Assertion](../client/identity-assertion.md)**.

## Zusammenfassung {#recap}

* Über Streamable HTTP ist dein Server ein OAuth-2.1-**Resource-Server**: Er prüft Tokens, er stellt nie welche aus.
* `TokenVerifier` ist die gesamte Integrationsfläche: eine asynchrone Methode, Token rein, `AccessToken | None` raus.
* `token_verifier=` und `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` treten immer gemeinsam auf.
* Das SDK veröffentlicht Protected Resource Metadata nach [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) unter `/.well-known/oauth-protected-resource/...` und beantwortet nicht authentifizierte Requests mit einer 401, deren `WWW-Authenticate`-Header darauf zeigt. Das ist die ganze Discovery-Geschichte.
* `get_access_token()` in jedem Handler sagt dir, wer aufruft.
* Autorisierung ist eine HTTP-Angelegenheit. `stdio` und der In-Memory-Client bekommen sie nie zu sehen.

Die Client-Hälfte (deinen Authorization Server finden und das Token für dich holen) steht unter **[OAuth-Clients](../client/oauth-clients.md)**. Und ein Client, der eine Identität *behauptet*, statt eine Person danach zu fragen, steht unter **[Identity Assertion](../client/identity-assertion.md)**.
