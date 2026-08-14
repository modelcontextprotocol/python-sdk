---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# Identity assertion {#identity-assertion}

साधारण OAuth provider (**[OAuth clients](oauth-clients.md)**) MCP server से एक सवाल पूछकर शुरू करता है: **आप किस authorization server पर भरोसा करते हैं?** जवाब जिधर इशारा करे, वह उधर चला जाता है, और फिर या तो कोई इंसान sign in करता है या उसकी जगह कोई pre-shared secret काम आता है।

Enterprise नहीं चाहता कि इनमें से कोई भी बात हर server के हिसाब से अलग तय हो। वह पहले से एक identity provider चलाता है (Okta, Microsoft Entra ID, या आपका अपना); user आज सुबह ही उसमें sign in कर चुका है; और यही वह एक जगह है जहाँ security team तय करना चाहती है कि कौन कहाँ तक पहुँच सकता है। [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990), यानी **Enterprise-Managed Authorization** extension, यह फ़ैसला वहीं ले जाता है। IdP एक short-lived JWT sign करता है, **Identity Assertion JWT Authorization Grant**, यानी **ID-JAG**: यह बयान कि **यह user**, **इस client** के ज़रिए, **इस MCP server** तक पहुँच सकता है। Client इसे देकर बदले में साधारण access token ले लेता है। न browser, न consent screen, न dynamic registration।

यह page उसी लेन-देन के दोनों सिरों के बारे में है। MCP server खुद कभी नहीं बदलता: वह अब भी **[Authorization](../run/authorization.md)** वाला resource server ही है, जो भी token सामने आए उसे जाँचता है।

## दो token requests {#two-token-requests}

यहाँ दो अलग-अलग authorities काम कर रही हैं, और उन्हें अलग-अलग नाम से पहचान लेना ही इस page को समझने का ज़्यादातर हिस्सा है। **Enterprise IdP** आपके organization का identity provider है: उसे पता है कि employee कौन है, policy वहीं रहती है, और ID-JAG वही जारी करता है। SDK उससे कभी बात नहीं करता। **MCP authorization server** वही पक्ष है जो **[Authorization](../run/authorization.md)** में था: MCP server के metadata में नामित issuer, वह चीज़ जो वे tokens बनाती है जिन्हें वह MCP server स्वीकार करता है। साधारण OAuth flow में ये दोनों भूमिकाएँ आमतौर पर एक ही system निभाता है। यहाँ ये दो हैं, और पूरा grant बस इतना है कि दूसरा पहले पर भरोसा करने को राज़ी हो।

Client इनमें से हर एक को एक token request भेजता है।

1. **Enterprise IdP को।** Client user के sign-in (उनका OpenID Connect ID token) के बदले ID-JAG लेता है। यह [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token exchange है, यह पूरी तरह आपके IdP का API है, और **SDK इसे नहीं करता**। यह आप करते हैं, एक async callback के अंदर। Policy का फ़ैसला भी यहीं होता है: जो IdP मना कर दे वह ID-JAG जारी ही नहीं करता, और पेश करने को कुछ बचता ही नहीं।
2. **MCP authorization server को।** Client ID-JAG को [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) `jwt-bearer` grant के तहत पेश करता है (`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, ID-JAG `assertion` के रूप में) और access token पाता है। **यही वह request है जो SDK भेजता है**, और इसे स्वीकार करना ही वह एक चीज़ है जो यह page authorization server में जोड़ता है।

नीचे सब कुछ दूसरी request के बारे में है: उसे भेजने वाला client और उसका जवाब देने वाला authorization server।

## Client {#the-client}

**`IdentityAssertionOAuthProvider`** `mcp.client.auth.extensions.identity_assertion` में रहता है। **[OAuth clients](oauth-clients.md)** के हर provider की तरह यह भी `httpx2.Auth` है: एक बनाएँ, उसे `auth=` पर रखें, और `httpx2.AsyncClient` transport को सौंप दें।

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

इसे नीचे से पढ़ें।

* `main()` वही standard OAuth-client वाला `main()` है (**[OAuth clients](oauth-clients.md)**), पंक्ति-दर-पंक्ति बिना बदलाव। यही बात है: एक बार provider बन जाए तो आगे किसी को पता नहीं चलता कि token किस grant से आया।
* Provider वह लेता है जो बाकी providers discover नहीं कर सकते: `client_id` और `client_secret` जो किसी ने authorization server के साथ **पहले से register** कर रखे हैं, उस authorization server का `issuer`, और `assertion_provider`, एक async callback जो माँगने पर ताज़ा ID-JAG लौटाता है।
* `storage` वही `TokenStorage` protocol है। सिर्फ़ दो token methods ही कभी call होते हैं; यहाँ dynamic registration नहीं है, इसलिए याद रखने को कोई `client_info` नहीं है।

### Assertion provider {#the-assertion-provider}

`fetch_id_jag(audience, resource)` ही वह इकलौता code है जो आप लिखते हैं। यह हर token exchange पर एक बार await होता है, construction के समय कभी नहीं, और सिर्फ़ तब **जब** authorization server का metadata fetch और validate हो चुका हो, इसलिए गलत configure किया गया issuer कभी assertion leak नहीं करवाता। इसके दो arguments उन claims में से दो हैं जिनके साथ ID-JAG बनना ज़रूरी है: `audience` authorization server का issuer है (ID-JAG का `aud`) और `resource` MCP server का canonical identifier है (ID-JAG का `resource`)। तीसरा वह है जो आपके पास पहले से है: ID-JAG के `client_id` claim में वही `client_id` होना चाहिए जो आपने provider को दिया, वरना authorization server exchange से मना कर देता है।

उसके ऊपर वाला `idp_issue_id_jag` **आपका code नहीं है**। वह identity provider की जगह खड़ा है, और assertion को उसी process में sign करता है ताकि file पूरी रहे और आप ID-JAG में जाने वाला हर claim पढ़ सकें। असली `fetch_id_jag` इसकी जगह पिछले section की पहली token request भेजता है: आपके IdP के सामने [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token exchange, जिसे Identity Assertion JWT Authorization Grant draft परिभाषित करता है और जिसे [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) profile करता है। Sign in किए हुए user का ID token `subject_token` के रूप में जाता है, `requested_token_type` ID-JAG का अपना URN है (`urn:ietf:params:oauth:token-type:id-jag`), `audience` और `resource` जस के तस आगे जाते हैं, और response में ID-JAG आता है। अपने IdP की documentation में इन्हीं नामों के साथ यही exchange ढूँढें।

!!! tip
    हर exchange के लिए ताज़ा ID-JAG माँगा जाता है, और यही मक़सद है: यह एक बार इस्तेमाल होने वाला,
    कुछ मिनट जीने वाला grant है, और इस page का authorization server एक ही ID-JAG को दो बार स्वीकार
    करने से मना कर देता है। इसे cache न करें। इसके बदले जो access token मिलता है, दोबारा इस्तेमाल वही होता है।

### Issuer configuration है {#the-issuer-is-configuration}

उलटफेर यहाँ है। `OAuthClientProvider` resource server से पूछता है कि कौन सा authorization server इस्तेमाल करे, और जवाब जिधर इशारा करे उधर चला जाता है। यह provider ऐसा करने से मना करता है: `issuer` ज़रूरी है, [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) metadata उसी issuer के अपने well-known path से fetch होता है, token endpoint उसी issuer के origin पर होना चाहिए, और resource server से कभी कुछ नहीं पूछा जाता।

Extension इसकी माँग नहीं करता; यह जान-बूझकर चुना गया ज़्यादा सख़्त रास्ता है। इस client के पास चुराने लायक दो चीज़ें हैं, एक pre-registered secret और एक audience-bound assertion, और जो client किसी compromised MCP server को खुद को हमलावर के authorization server की तरफ़ मोड़ने दे, वह दोनों उसी को post कर देगा। Construction के समय issuer को pin कर देने से वह बातचीत ही ख़त्म हो जाती है।

!!! warning
    Configure किए गए `issuer` की तुलना metadata document के `issuer` field से RFC 8414 §3.3 के
    simple string comparison से होती है: एक-एक character, आख़िरी slash समेत, बिना किसी normalization के।
    इसका अंदाज़ा न लगाएँ। अपने authorization server से `/.well-known/oauth-authorization-server` fetch करें
    और जो `issuer` value वह लौटाए उसे copy करें। इस page के authorization server के लिए वह
    `https://auth.example.com/` है, slash के साथ, क्योंकि उसका issuer pydantic URL object से बना था।
    Mismatch होने पर flow एक भी credential या assertion भेजे जाने से पहले `OAuthFlowError: Authorization server metadata issuer
    mismatch` पर रुक जाता है।

### Confidential client {#a-confidential-client}

`client_secret` ज़रूरी है; इसके बिना constructor `ValueError` raise करता है। [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) के नीचे वाला IETF profile इस grant को confidential clients के लिए आरक्षित रखता है, SEP-990 client से authenticate करने की माँग करता है, और यह SDK shared secret पर ज़ोर देकर दोनों लागू करता है। `token_endpoint_auth_method` तय करता है कि यह कहाँ से होकर जाए: `client_secret_post` (default, form body में) या `client_secret_basic` (HTTP Basic header)। Profile `private_key_jwt` की भी इजाज़त देता है; यह provider उसे support नहीं करता।

!!! tip
    `client_secret` को environment या किसी secret manager से पढ़ें, source control से कभी नहीं।

### Provider आपके लिए क्या करता है {#what-the-provider-does-for-you}

पहली request बिना authentication के जाती है, और server का `401` flow शुरू करता है।

1. **Discovery।** यह configure किए गए issuer के [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known path से authorization server metadata fetch करता है, जाँचता है कि document का `issuer` मेल खाता है, और जाँचता है कि token endpoint issuer के origin पर है।
2. **Assertion।** यह आपके `assertion_provider` को await करता है।
3. **Exchange।** यह token endpoint पर `jwt-bearer` grant POST करता है, `OAuthToken` store करता है, और आपकी मूल request `Authorization: Bearer ...` के साथ दोबारा भेजता है।

जिस `403` का `WWW-Authenticate` `insufficient_scope` बताता है, वह चरण 2 और 3 को आपके `scope` और challenge किए गए scope के union के साथ दोबारा चलाता है। (`scope` हमेशा सिर्फ़ एक माँग है; इस page का authorization server वही देता है जो ID-JAG कहता है, उससे ज़्यादा कुछ नहीं।) इसमें कहीं कोई refresh token नहीं है: access token expire होने पर अगला `401` ताज़ा ID-JAG बनवाता है और फिर exchange करता है, और **यही** वह lever है जो IdP के हाथ में है। नाकामियाँ **[OAuth clients](oauth-clients.md)** के बाकी हिस्से वाले वही दो exceptions हैं: discovery और validation के लिए `OAuthFlowError`, और जब token endpoint मना करे तब उसका subclass `OAuthTokenError`।

## Authorization server {#the-authorization-server}

ज़्यादातर बार आप यहीं रुक जाते हैं। MCP authorization server किसी और का product है, ID-JAGs स्वीकार करना उसकी configuration में चालू करने की चीज़ है, और [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) का SDK वाला आधा हिस्सा ऊपर का client है।

SDK खुद authorization server भी **बन** सकता है: `create_auth_routes` authorization server के routes एक list के रूप में लौटाता है जिसे कोई भी Starlette app mount कर सकता है; repository में `examples/servers/simple-auth/` इसी तरह एक चलाता है। SEP-990 उस surface में एक flag और एक method जोड़ता है:

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` सब कुछ gate करता है। बंद होने पर, जो default है, `/token` इस grant का जवाब `unsupported_grant_type` से देता है चाहे आपने hook implement किया हो, और metadata में इसका ज़िक्र नहीं होता। चालू होने पर metadata में `jwt-bearer` grant type जुड़ जाता है और `authorization_grant_profiles_supported` में `urn:ietf:params:oauth:grant-profile:id-jag` सूचीबद्ध हो जाता है; यही वह field है जिससे extension support का ऐलान करता है। (इस SDK का client इसे कभी नहीं पढ़ता: वह एक issuer के लिए provision किया गया है और सीधे माँग लेता है।)
* **`exchange_identity_assertion`** ही hook है। इसके चलने से पहले SDK client को authenticate कर चुका होता है, public clients को मना कर चुका होता है, और उन clients को मना कर चुका होता है जिनके registration में यह grant सूचीबद्ध नहीं है। आपको `IdentityAssertionParams` मिलता है (कच्चा `assertion`, माँगे गए `scopes` और `resource`) और आप सादा `OAuthToken` लौटाते हैं।
* Dynamic client registration इस grant को बिना शर्त मना करता है, इसलिए यहाँ `get_client` हाथ से provision किया गया client देता है। ID-JAG client खुद को register करके अस्तित्व में नहीं ला सकता।
* आधी class इनकारों से भरी है। `OAuthAuthorizationServerProvider` **पूरा** authorization server है, इसलिए वह authorization-code flow भी माँगता है; जो server users को sign in भी कराता है वह उन्हें सच में implement करता है, और इस वाले में ठीक एक ही दरवाज़ा है।

!!! warning
    SDK assertion को कभी decode नहीं करता: सिर्फ़ आपके deployment को पता है कि वह किस IdP पर भरोसा करता है
    और वह IdP कौन सी keys publish करता है, इसलिए `exchange_identity_assertion` के अंदर की हर चीज़ पर पूरा भार टिका है।
    Signature को IdP की published keys (उसकी JWKS; यहाँ वाला shared secret demo का है) से verify करें,
    और [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3 के मुताबिक `iss` और `exp` भी। JWT header का `typ`
    `oauth-id-jag+jwt` होना ज़रूरी करें; यह profile का बचाव है ताकि कोई और JWT grant बनाकर replay न किया जा सके।
    `aud` आपका अपना issuer हो, यह ज़रूरी करें। ID-JAG का `client_id` claim उसी client के बराबर हो जिसे
    handler ने authenticate किया, और उसका `resource` claim किसी ऐसे resource का नाम ले जिसे आप सच में serve करते हैं,
    यह ज़रूरी करें। `jti` को assertion के `exp` तक track करें ताकि वह एक ही बार स्वीकार हो। और दिए गए scopes,
    और सबसे बढ़कर जारी किए गए token का `resource`, validated ID-JAG से लें, request से कभी नहीं:
    `params.resource` वही है जो client ने type किया। Processing के पूरे नियम
    [Enterprise-Managed Authorization specification](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization) में हैं।

ख़राब assertion को `TokenError("invalid_grant", ...)` से reject करें। इस flow का दूसरा error code `invalid_target` है: जो ID-JAG किसी ऐसे resource का नाम ले जिसे आप serve नहीं करते, उसे इसी से मना किया जाता है, और यही इस server को किसी और के resource के लिए tokens बनाने से रोकता है। और दिए गए scopes ID-JAG के `scope` claim से आते हैं (जिस assertion में यह न हो उसे भी मना किया जाता है); आपका server शायद इसकी जगह user के groups map करे।

और ध्यान दें कि लौटाए गए `OAuthToken` में क्या नहीं है: refresh token। IdP यह तय करके कि अगला ID-JAG जारी करना है या नहीं, तय करता है कि इस user की पहुँच कब तक बनी रहे। यहाँ बना refresh token वह फ़ैसला चुपचाप वापस सौंप देता।

!!! info
    जो server अब भी `auth_server_provider=` से अपना authorization server embed करता है, वह
    `AuthSettings(identity_assertion_enabled=True)` के ज़रिए इसी code तक पहुँचता है। **[Authorization](../run/authorization.md)** समझाता है कि नए
    servers को वहाँ से शुरू क्यों नहीं करना चाहिए।

!!! check
    इस page की दोनों files को आपस में जोड़ दें और पूरा grant बस एक `POST /token` है:

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

    न `/authorize`, न `/register`, न protected-resource-metadata fetch। Wire पर सिर्फ़ ये requests हैं:
    वह जिस पर `401` आया, well-known fetch, यह exchange, और फिर bearer लगा हुआ साधारण
    MCP traffic। और जो `sub` आपके validator ने ID-JAG से पढ़ा, tool के अंदर
    `get_access_token().subject` ठीक वही बताता है।

### इसे आज़माएँ {#try-it}

SDK repository में `examples/stories/identity_assertion/` यही page असल में चलता हुआ है: वही `exchange_identity_assertion` validator, उसके tokens पर gate किया गया MCP server, एक stand-in IdP, और client, सब एक self-checking program में। `uv run python -m stories.identity_assertion.client --http` पूरा exchange चलाता है और assert करता है कि जिस user का नाम IdP ने लिया, tool को वही user दिखता है।

## सारांश {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) यह फ़ैसला end user के बजाय enterprise identity provider को करने देता है कि client किन MCP servers तक पहुँच सकता है। IdP उस फ़ैसले को sign करके **ID-JAG** में डाल देता है।
* ID-JAG हासिल करना **आपके IdP** के सामने [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token exchange है, और SDK इसे नहीं करता। उसे MCP authorization server के सामने पेश करना [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) `jwt-bearer` grant है, और SDK उसके दोनों पक्ष करता है।
* `IdentityAssertionOAuthProvider` एक और `httpx2.Auth` है: pre-registered confidential client, pin किया गया `issuer`, और एक `assertion_provider(audience, resource)` callback। न browser, न registration, न refresh token।
* Authorization server कभी resource server से discover नहीं होता। `issuer` को ठीक उसी string पर configure करें जो उसका metadata document देता है; तुलना एक-एक character की होती है।
* Server की तरफ़, `identity_assertion_enabled=True` और `exchange_identity_assertion`। SDK client को authenticate करता है और grant को gate करता है; ID-JAG validate करना पूरी तरह आपका काम है, और जारी किया गया token ID-JAG के `resource` से बँधा होता है, request के नहीं।

इकलौता पक्ष जिसे इस page ने कभी नहीं छुआ, वह MCP server है। अभी-अभी बनाए गए token के साथ वह जो करता है, वह **[Authorization](../run/authorization.md)** में पहले से कर ही रहा था।
