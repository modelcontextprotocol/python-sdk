---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth clients {#oauth-clients}

कुछ MCP servers सुरक्षित होते हैं। उन्हें बिना token के request भेजें तो जवाब `401 Unauthorized` आता है।

token पाने का तरीका **`OAuthClientProvider`** है। यह कोई MCP object है ही नहीं। यह `httpx2.Auth` है, "हर request के साथ कुछ करो" वाला httpx2 का standard hook। इसे `httpx2.AsyncClient` पर लगाएँ, वह client Streamable HTTP transport को दें, और इसके बारे में सोचना बंद कर दें।

यह page client वाला हिस्सा है। अपने server से token की माँग करवाना **[Authorization](../run/authorization.md)** में है।

## Provider {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

आप इसे चार चीज़ें देते हैं:

* `server_url`: वह MCP endpoint जिससे आप जुड़ रहे हैं। बाकी सब कुछ provider इसी से खोज लेता है।
* `client_metadata`: वही जो आप किसी authorization server के "register an application" form में भरते।
* `storage`: जहाँ दो runs के बीच tokens रहते हैं।
* `redirect_handler` और `callback_handler`: वे दो पल जिनमें कोई इंसान शामिल होता है।

file में और कहीं OAuth का ज़िक्र नहीं है। `main()` को कभी कोई token दिखता ही नहीं।

### Client metadata {#client-metadata}

`OAuthClientMetadata` असली [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) registration document है, Pydantic model के रूप में।

आप तीन fields भरते हैं। बाकी defaults भर देते हैं: `grant_types` पहले से `["authorization_code", "refresh_token"]` है और `response_types` पहले से `["code"]` है, ठीक वही flow जो यह provider चलाता है।

!!! check
    चूँकि यह Pydantic model है, यह **network पर एक भी byte जाने से पहले** validate करता है।
    `redirect_uris` छोड़ दें तो construction वहीं के वहीं `ValidationError` के साथ fail हो जाता है,
    जो field का नाम बताता है:

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    न कोई browser खुला, न authorization server पर कोई अधूरी registration पीछे छूटी।

### Token storage {#token-storage}

**`TokenStorage`** चार async methods वाला `Protocol` है। आपको किसी से inherit नहीं करना; methods लिख दें और कोई भी class token store बन जाती है:

* `get_tokens` / `set_tokens` `OAuthToken` रखते हैं: access token, refresh token, expiry, scope।
* `get_client_info` / `set_client_info` वह `OAuthClientInformationFull` रखते हैं जो authorization server ने तब जारी किया था जब provider ने आपको register किया, आपके `client_id` समेत।

ऊपर वाला in-memory version काम करता है। यह process के ख़त्म होते ही सब कुछ भूल भी जाता है, इसलिए अगला run पूरी प्रक्रिया फिर से दोहराता है। इसे किसी file या अपने platform के keyring में persist करें और अगला run चुपचाप चल जाता है।

!!! tip
    सिर्फ़ tokens नहीं, `client_info` भी store करें। provider पहली बार तब dynamically register करता है
    जब उसे कोई stored `client_info` नहीं मिलता। इसे फेंक दें तो हर run पर एक नई registration बनती है।

### दो handlers {#the-two-handlers}

authorization code flow को इंसान की ज़रूरत ठीक एक बार पड़ती है: किसी को sign in करके "allow" पर click करना होता है।

* **`redirect_handler`** को पूरी तरह बने हुए authorization URL के साथ await किया जाता है। `client_id`, `redirect_uri`, `state` और PKCE challenge उसमें पहले से मौजूद हैं। आपका काम बस इतना है कि browser को वहाँ पहुँचाएँ। desktop app `webbrowser.open` call करता है; यह file उसे print कर देती है।
* उसके बाद **`callback_handler`** await होता है। यह तब तक इंतज़ार करता है जब तक user वापस आपके `redirect_uri` पर नहीं पहुँच जाता, और उस redirect के query parameters को `AuthorizationCodeResult` के रूप में लौटाता है।

असली client `input()` call करने के बजाय redirect URI पर एक छोटा local HTTP server चलाता है। आकार बिल्कुल वही है: redirect हों, और `code`, `state` व `iss` वापस दें।

!!! warning
    `state` और `iss` को ठीक वैसे ही आगे दें जैसे वे आए थे। provider `state` की तुलना उससे करता है
    जो उसने खुद बनाया था, और `iss` की तुलना खोजे गए issuer से, और मेल न खाने पर मना कर देता है।
    यही CSRF और server-mix-up से बचाव हैं।

### `Client` में {#into-the-client}

`main()` देखें। provider **httpx2 client** पर जाता है, httpx2 client `streamable_http_client(url, http_client=...)` में जाता है, और वह transport `Client` में जाता है।

`streamable_http_client` में `auth=` keyword नहीं है। HTTP स्तर की हर चीज़ (auth, headers, timeouts, proxies) उस `httpx2.AsyncClient` पर होती है जो आप लाते हैं। यह layering **[Client transports](transports.md)** में है।

## Provider आपके लिए क्या करता है {#what-the-provider-does-for-you}

जब `Client` पहली बार request भेजता है, server `401` लौटाता है। provider कमान संभाल लेता है:

1. **Discovery.** यह `WWW-Authenticate` header पढ़ता है, `/.well-known/oauth-protected-resource` से server का Protected Resource Metadata लाता है, पता करता है कि कौन सा authorization server इस resource की रक्षा करता है, और **उस** server का metadata लाता है।
2. **Registration.** storage में कुछ नहीं है? यह आपके `OAuthClientMetadata` के साथ आपको dynamically register करता है और नतीजा store कर लेता है।
3. **Authorization.** यह PKCE pair और `state` बनाता है, authorization URL तैयार करता है, आपके `redirect_handler` को await करता है, फिर code के लिए आपके `callback_handler` को await करता है।
4. **Exchange.** यह code के बदले `OAuthToken` लेता है, उसे store करता है, और आपकी मूल request को `Authorization: Bearer ...` के साथ दोबारा भेजता है।

उसके बाद यह शांत रहता है। tokens storage से आते हैं, expire हुआ access token refresh token से refresh हो जाता है, और सिर्फ़ तब जब इनमें से कुछ काम नहीं करता, यह flow फिर से चलाता है।

आपने इसमें से कुछ नहीं लिखा। दो keyword arguments बचते हैं (`client_metadata_url` और `validate_resource_url`), और इस file को दोनों में से किसी की ज़रूरत नहीं। `client_metadata_url` जानने लायक है; इसका अपना section नीचे है।

### इसे आज़माएँ {#try-it}

इन docs के ज़्यादातर उदाहरण आप in-memory `Client(server)` से जाँच सकते हैं। यह नहीं: इस flow का पूरा मतलब ही HTTP `401` है, और in-memory client व उसके server के बीच कोई HTTP होता ही नहीं।

repository में live version मौजूद है। `examples/servers/simple-auth/` एक standalone authorization server और एक protected MCP server चलाता है; `examples/clients/simple-auth-client/` इसी page का client है, छोटी CLI में बढ़ा हुआ। उसकी README में दो commands हैं: servers शुरू करें, client को उनके सामने चलाएँ, और चारों चरण अपनी आँखों के सामने होते देखें।

## Client ID Metadata Documents {#client-id-metadata-documents}

spec का 2026-07-28 revision dynamic client registration को **Client ID Metadata Documents** (CIMD) के पक्ष में deprecated कर देता है। जिस भी authorization server से मिले उस पर नई registration POST करने के बजाय, आपका client अपने बारे में एक JSON document किसी स्थिर HTTPS URL पर publish करता है, और वही URL उसका `client_id` **है**। authorization server वह document लाता है; provider उसे कभी छूता तक नहीं।

SDK पहले से इसे समझता है: provider बनाते समय URL को `client_metadata_url=` के रूप में दें। जब authorization server का metadata `client_id_metadata_document_supported: true` बताता है, provider `/register` request को पूरी तरह छोड़ देता है: URL `client_id` बनकर flow में जाता है, और कोई `client_secret` नहीं होता। जब server इसे नहीं बताता (ज़्यादातर अभी नहीं बताते), या आप URL देते ही नहीं, तो provider **चुपचाप** dynamic registration पर लौट आता है, और ऊपर बताया सब कुछ ठीक वैसे ही काम करता है। stored `client_info` अब भी दोनों पर भारी पड़ती है।

URL HTTPS होना चाहिए और उसका path root न हो; इसके अलावा कुछ भी construction पर `ValueError` है, किसी network गतिविधि से पहले। साथ आने वाला `examples/clients/simple-auth-client/` इसे `MCP_CLIENT_METADATA_URL` environment variable के रूप में लेता है।

## Machine to machine {#machine-to-machine}

रात को चलने वाला job, CI का कोई step, कोई दूसरी service। न browser है, न "allow" पर click करने वाला कोई। यही **client credentials** grant है: आपके पास पहले से `client_id` और `client_secret` हैं, और token endpoint ही पूरा flow है।

`ClientCredentialsOAuthProvider` वही `httpx2.Auth` है, बस इंसान के बिना:

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

क्या बदला:

* न `OAuthClientMetadata`, न handlers। आप `client_id` और `client_secret` देते हैं; provider उनके इर्द-गिर्द एक न्यूनतम `client_credentials` registration बनाता है और dynamic registration पूरी तरह छोड़ देता है।
* `scope` space से अलग की गई string है, OAuth का wire format।
* आगे का सब कुछ बिल्कुल वही है: वही `TokenStorage`, वही `httpx2.AsyncClient(auth=...)`, वही `streamable_http_client`।

default रूप से secret token request पर HTTP Basic auth के रूप में जाता है (`client_secret_basic`)। उसे form body में डालने के लिए `token_endpoint_auth_method="client_secret_post"` दें। कुछ authorization servers दोनों में से सिर्फ़ एक ही स्वीकार करते हैं।

!!! tip
    `client_secret` को environment या किसी secret manager से पढ़ें, source control से कभी नहीं।

!!! info
    एक और provider `mcp.client.auth.extensions.client_credentials` में रहता है:
    **`PrivateKeyJWTOAuthProvider`**, उन clients के लिए जो shared secret के बजाय JWT से
    authenticate करते हैं (`private_key_jwt`, key-pair और workload-identity वाला रूप)। यह उसी
    pattern पर चलता है: एक बनाएँ, `auth=` पर लगाएँ। उसी module में
    `SignedJWTParameters` और `static_assertion_provider` भी हैं, दो helpers जो इसका assertion बनाते हैं।

बिना इंसान वाली एक और स्थिति है: client किसी enterprise का है जिसका identity provider, न कि user, तय करता है कि वह किन MCP servers तक पहुँच सकता है। वह अलग grant है, अपने trust model और अपने page के साथ, **[Identity assertion](identity-assertion.md)**।

## जब यह fail होता है {#when-it-fails}

जब OAuth flow में गड़बड़ होती है, provider `mcp.client.auth` से `OAuthFlowError` raise करता है। इसके दो subclasses हैं। `OAuthRegistrationError` का मतलब है कि registration से ऐसा client नहीं मिला जिसे आप इस्तेमाल कर सकें: authorization server ने आपको register करने से मना कर दिया, या register तो किया लेकिन ऐसे credentials के साथ जो यह flow इस्तेमाल नहीं कर सकता (उदाहरण के लिए कोई authentication method जिसे यह implement नहीं करता)। `OAuthTokenError` का मतलब है कि token नहीं मिल सका: token endpoint ने मना कर दिया, या किसी stored client record में ऐसा authentication method है जिसे यह client लागू नहीं कर सकता, जिसकी report token request बनाते समय होती है, भेजी नहीं जाती। एक `except OAuthFlowError:` discovery, registration, authorization और exchange, सबको cover करता है।

हर चीज़ flow error नहीं होती। network अब भी fail हो सकता है; वे साधारण `httpx2` exceptions हैं और बिना छुए आगे निकल जाते हैं।

## सारांश {#recap}

* `OAuthClientProvider` `httpx2.Auth` है। इसे `httpx2.AsyncClient` पर लगाएँ, उसे `streamable_http_client(url, http_client=...)` को दें, और `Client` को कभी पता नहीं चलता कि OAuth हुआ।
* आप चार चीज़ें देते हैं: server URL, एक `OAuthClientMetadata`, एक `TokenStorage`, और redirect/callback handler की जोड़ी।
* `TokenStorage` `Protocol` है: चार async methods, कोई base class नहीं। tokens के साथ-साथ `client_info` भी persist करें।
* discovery, registration (dynamic, या **Client ID Metadata Document** के ज़रिए), PKCE, `state` और `iss` की जाँच, और token refresh provider का काम हैं, आपका नहीं।
* `ClientCredentialsOAuthProvider` बिना इंसान वाला version है: `client_id` + `client_secret`, न handlers, न browser।
* हर OAuth failure `OAuthFlowError` है; `OAuthRegistrationError` और `OAuthTokenError` इसके subclasses हैं।

इस handshake का दूसरा हिस्सा, अपने **server** से token की माँग करवाना, **[Authorization](../run/authorization.md)** में है।
