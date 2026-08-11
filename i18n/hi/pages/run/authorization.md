---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# Authorization {#authorization}

Streamable HTTP पर आपका MCP server साधारण web service ही है, और आप इसे उसी तरह सुरक्षित करते हैं जैसे किसी भी web service को: OAuth 2.1 bearer tokens से।

OAuth की भाषा में, आपका server **resource server** है। यह न किसी को sign in कराता है, न कभी कोई token जारी करता है। यह बस एक काम करता है: हर request पर `Authorization` header देखता है और तय करता है कि उसमें रखा token सही है या नहीं।

यह page server side के बारे में है। जो client आपके authorization server को खोजता है और token लाता है, उसकी जानकारी **[OAuth clients](../client/oauth-clients.md)** में है।

## तीन पक्ष {#the-three-parties}

* **authorization server** लोगों को sign in कराता है और access tokens जारी करता है। इसे आप नहीं लिखते। यह आपका identity provider है (Auth0, Keycloak, Entra, या आपका अपना)।
* **resource server** आपका MCP server है। यह हर request पर token verify करता है।
* **client** पता लगाता है कि आप किस authorization server पर भरोसा करते हैं, उससे token लेता है, और उसे `Authorization: Bearer <token>` के रूप में आपको वापस भेजता है।

पूरा त्रिकोण बस इतना ही है। इस page पर जो कुछ है, वह बीच वाला bullet है।

## Token verifier {#a-token-verifier}

valid token कैसा दिखता है, इस बारे में SDK की कोई राय नहीं है। यह आप बताते हैं, **`TokenVerifier`** implement करके:

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` एक async method वाला protocol है। `verify_token` को `Authorization` header से raw token मिलता है, और token valid हो तो यह **`AccessToken`** लौटाता है, न हो तो `None`। इसके अलावा implement करने को कुछ नहीं है।
* यह वाला token को एक table में ढूँढता है। असली verifier JWT signature verify करता है या authorization server के token-introspection endpoint को call करता है। वह code आपका है; SDK उसे सिर्फ़ call करता है।
* `token_verifier=` और `auth=` हमेशा साथ चलते हैं। एक को दूसरे के बिना pass करें तो `MCPServer(...)` कोई request serve करने से पहले ही `ValueError` raise कर देता है।

`AuthSettings` आपके resource server का सार्वजनिक चेहरा है:

* `issuer_url`: वह authorization server जो आपके tokens जारी करता है।
* `resource_server_url`: इस MCP endpoint का public URL। यह बताता है कि token **किस** resource के लिए है, और discovery document भी यहीं रहता है।
* `required_scopes`: हर token में ये सभी होने ही चाहिए।

!!! tip
    SDK repository में `examples/servers/simple-auth/` के अंदर एक `IntrospectionTokenVerifier` है जो
    असली authorization server के [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) endpoint को call करता है। ज़्यादातर production verifiers का आकार यही होता है।

## HTTP पर आपको क्या मिलता है {#what-you-get-over-http}

authorization HTTP headers में रहता है, इसलिए यह सिर्फ़ HTTP transports पर मौजूद है। इसे उसी transport पर चलाएँ जिसे आप deploy करते हैं: `mcp.run(transport="streamable-http")` इसे `http://127.0.0.1:8000/mcp` पर रखता है, और बाकी जानकारी **[अपना server चलाना](index.md)** में है। app के पास अब दो routes हैं:

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

आपने एक tool register किया था। दूसरा route SDK का है।

### Discovery {#discovery}

उस well-known path पर `GET` करें और आपको **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata** मिलता है, जो सीधे आपके `AuthSettings` से बना है:

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

जिस client ने आपके server के बारे में कभी सुना भी नहीं, वह इसी document के सहारे अंदर का रास्ता ढूँढता है: वह `authorization_servers` पढ़ता है और token के लिए वहाँ जाता है। इसमें से कुछ भी आपने नहीं लिखा।

!!! check
    `/mcp` को बिना token के call करें (या ऐसे token के साथ जिसके लिए आपके verifier ने `None` लौटाया) और request
    दरवाज़े पर ही रोक दी जाती है:

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    न कुछ parse हुआ, न कोई tool चला। और `WWW-Authenticate` में जो `resource_metadata` pointer है, वही
    discovery को automatic बनाता है: 401 -> metadata document -> authorization server -> token -> retry।

!!! warning
    इनमें से कुछ भी `stdio` को सुरक्षित नहीं करता। pipe में कोई `Authorization` header नहीं होता, इसलिए वहाँ `token_verifier` से कभी
    पूछा ही नहीं जाता। `stdio` server की सुरक्षा सीमा वह process है जिसने उसे शुरू किया। यही बात
    tests में इस्तेमाल होने वाले in-memory `Client(mcp)` पर भी लागू होती है: वह सीधे server object से जुड़ता है
    और HTTP layer को, authorization समेत, छोड़ देता है।

## caller की पहचान {#the-callers-identity}

किसी भी handler के अंदर, **`get_access_token()`** वही `AccessToken` है जो आपके verifier ने मौजूदा request के लिए लौटाया था:

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* यह tools, resources और prompts में काम करता है, और कुछ इधर-उधर pass करने की ज़रूरत नहीं: auth middleware इसे हर request के लिए एक context variable में रखता है।
* आपको **वही object वापस मिलता है जो आपके verifier ने बनाया था**: `client_id`, `scopes`, `subject`, `expires_at`, और जो भी अतिरिक्त `claims` आपने जोड़े। per-tool नियमों के लिए यही hook है: scopes पढ़ें और मना कर दें।
* authenticated HTTP request के बाहर यह `None` लौटाता है। in-memory और `stdio` पर यह हमेशा `None` है।

`Authorization: Bearer alice-token` के साथ `whoami` call करें और model को यह पढ़ने को मिलता है:

```text
alice (scopes: notes:read)
```

## वह आधा हिस्सा जो SDK नहीं करता {#the-half-the-sdk-doesnt-do}

SDK आपको resource-server वाला आधा हिस्सा देता है: verify करना, advertise करना, मना करना। यह आपको न login page देता है, न consent screen, न token।

तीनों पक्षों को काम करते देखना हो तो SDK repository से `examples/servers/simple-auth/` चलाएँ (एक छोटा authorization server और ठीक इस page की तरह set up किया गया resource server) और फिर discovery-और-token के पूरे क्रम के लिए `examples/clients/simple-auth-client/` को उसकी ओर point करें।

!!! info
    constructor का एक दूसरा argument भी है, `auth_server_provider=`, जो आपके MCP server के अंदर पूरा authorization
    server embed कर देता है। यह उस AS/RS अलगाव से पहले का है जिसके इर्द-गिर्द MCP authorization spec
    बना है। नए servers को इसकी ओर हाथ नहीं बढ़ाना चाहिए।

authorization server, user के consent screen पर click करने की जगह, किसी enterprise identity provider का signed assertion भी स्वीकार कर सकता है, और SDK उस आदान-प्रदान के दोनों पक्षों को support करता है। वह grant, और उसे पेश करने वाला client, **[Identity assertion](../client/identity-assertion.md)** में है।

## सारांश {#recap}

* Streamable HTTP पर आपका server OAuth 2.1 **resource server** है: यह tokens verify करता है, जारी कभी नहीं करता।
* पूरा integration surface बस `TokenVerifier` है: एक async method, token अंदर, `AccessToken | None` बाहर।
* `token_verifier=` और `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` हमेशा साथ चलते हैं।
* SDK `/.well-known/oauth-protected-resource/...` पर [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata publish करता है और unauthenticated requests का जवाब 401 से देता है, जिसका `WWW-Authenticate` header उसी की ओर इशारा करता है। discovery की पूरी कहानी बस इतनी ही है।
* किसी भी handler में `get_access_token()` बताता है कि call कौन कर रहा है।
* authorization HTTP का मामला है। `stdio` और in-memory client इसे कभी नहीं देखते।

client वाला आधा हिस्सा (आपके authorization server को खोजना और आपके लिए token लाना) **[OAuth clients](../client/oauth-clients.md)** में है। और जो client user से पहचान पूछने के बजाय खुद कोई पहचान **assert** करता है, वह **[Identity assertion](../client/identity-assertion.md)** में है।
