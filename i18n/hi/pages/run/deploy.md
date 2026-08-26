---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# Deploy और scale करना {#deploy-scale}

आपका server काम कर रहा है। अब इसे असली hostname चाहिए, और उसके पीछे एक से ज़्यादा worker।

इसमें से लगभग कुछ भी MCP का काम नहीं है। ASGI server, process manager, load balancer — ये आप लाते हैं। इस page पर उन थोड़ी-सी चीज़ों की छोटी सूची है जो सच में MCP का काम **हैं**: एक setting जो हर deployment का रास्ता रोकती है, और वे दो जगहें जहाँ "एक से ज़्यादा worker" होने पर SDK का व्यवहार बदल जाता है।

## सबसे पहले: Host allowlist {#before-anything-else-the-host-allowlist}

`streamable_http_app()` यह नहीं जान सकता कि उसे किस hostname के पीछे serve किया जाएगा, इसलिए वह सबसे सुरक्षित जवाब मान लेता है: localhost। `transport_security=` न दिया हो तो app **DNS-rebinding protection** चालू कर देता है और कोई request तभी स्वीकार करता है जब उसका `Host` header `127.0.0.1:<port>`, `localhost:<port>`, या `[::1]:<port>` हो। `Origin` header, जब मौजूद हो, तो उसी का `http://` रूप होना चाहिए। आपकी मशीन पर यह बिल्कुल सही है: यह किसी दुर्भावनापूर्ण web page को ऐसे DNS नाम के ज़रिए आपका local server चलाने से रोकता है जिसे उसने `127.0.0.1` पर rebind कर दिया हो।

असली hostname के पीछे deploy होने पर वही default **हर request** को ठुकरा देता है, जब तक आप कुछ और न कहें। यह जाँच MCP से जुड़ी किसी भी चीज़ से पहले चलती है, इसलिए आपने जो बनाया उससे पूछा तक नहीं जाता:

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

इसका इलाज `transport_security=` है। जो आप सच में serve करते हैं उसे allowlist करें:

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* `allowed_hosts` की entries हूबहू strings हैं: `"mcp.example.com"` बिना port वाले `Host` header से मेल खाती है और `"mcp.example.com:*"` किसी भी port से। दोनों लिखें।
* `allowed_origins` सिर्फ़ browsers के लिए मायने रखती है, क्योंकि और कोई `Origin` नहीं भेजता। यह **[मौजूदा app में जोड़ना](asgi.md)** में बताई गई CORS configuration का server-side जोड़ीदार है।
* ऐसे reverse proxy के पीछे जो पहले से `Host` header को नियंत्रित करता है, इस जाँच को बंद कर देना ही ईमानदार configuration है: `TransportSecuritySettings(enable_dns_rebinding_protection=False)`।
* localhost से अलग `host=` देना (जैसे `host="mcp.example.com"`) उस hostname को allowlist **नहीं** करता। इससे बस इतना होता है कि localhost वाला default protection चालू नहीं करता, यानी हर Host और Origin स्वीकार हो जाता है। इसके बजाय `transport_security=` से साफ़-साफ़ कहें कि आप क्या चाहते हैं।

!!! check
    `transport_security=security` argument हटा दें और app को फिर भी deploy करें। वह शुरू होता है, `/mcp`
    route होता है, और हर request (सादे `curl` से भेजी गई भी) का यह जवाब आता है:

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    client की तरफ़ आपको ये शब्द नहीं मिलेंगे। `421` plain-text HTTP response है, JSON-RPC error नहीं,
    इसलिए MCP client एक सामान्य transport error raise करता है; जो hostname उसे पसंद नहीं आया
    वह सिर्फ़ **server** के log में दिखता है, एक अकेली warning के रूप में। नया-नया
    deploy हुआ server जो हर connection ठुकरा रहा हो, उसे Host allowlist की समस्या ही मानें जब तक कुछ और साबित न हो।
    **[Troubleshooting](../troubleshooting.md)** भी यहीं से शुरू होता है।

## Workers, और sticky किसे होना है {#workers-and-who-has-to-be-sticky}

जब hostname जवाब देने लगे, तो उसके पीछे एक से ज़्यादा worker लगाएँ। इसके लिए SDK में कोई knob नहीं है; Starlette app को वैसे ही scale किया जाता है जैसे किसी भी ASGI app को, object किसी ऐसी चीज़ को सौंपकर जो fork करना जानती है:

```console
uvicorn server:app --workers 4
```

चार processes, एक socket। और अब वह सवाल जिसका जवाब हर deployment को देना होता है: **क्या किसी request का उसी worker तक पहुँचना ज़रूरी है जिसने पिछली request देखी थी?**

**2026-07-28** protocol बोलने वाले client के लिए, नहीं। modern request अपने आप में पूरी एक POST है: उससे पहले कोई `initialize` handshake नहीं, response पर कोई `Mcp-Session-Id` नहीं, ऐसा कुछ भी नहीं जिस पर दूसरी request को लौटकर आना पड़े। इसे किसी भी worker को भेज दें।

यह कोई ऐसा mode नहीं जिसे आप चालू करते हैं। `stateless_http=True` देखने में ऐसा लगता है, लेकिन transport `MCP-Protocol-Version` request header देखकर route करता है, modern request को modern handler को सौंपता है, और **return कर जाता है**। `stateless_http` पढ़ने वाली line उस return के **बाद** आती है। ऐसा नहीं कि 2026-07-28 path पर flag अनदेखा होता है; वहाँ तक पहुँचा ही नहीं जाता। `stateless_http` सिर्फ़ **legacy** हिस्से का knob है, और modern path बनावट से ही sessionless है।

spec version 2025-11-25 या उससे पहले वाले legacy client के लिए जवाब उस flag पर निर्भर करता है:

| client का protocol version | Session | load balancer को क्या करना होगा |
| --- | --- | --- |
| **2026-07-28** | कोई नहीं। `Mcp-Session-Id` कभी set नहीं होता। | कुछ नहीं। कोई भी worker कोई भी request serve करता है। |
| **2025-11-25 और पहले** (default) | `Mcp-Session-Id`, एक worker की memory में रखा हुआ। | **Sticky sessions।** कोई अगली request जो दूसरे worker तक पहुँचे उसे `404` *"Session not found"* मिलता है। |
| **2025-11-25 और पहले**, `stateless_http=True` के साथ | कोई नहीं। | कुछ नहीं। कीमत है server से client वाला back-channel (sampling, push elicitation, `roots/list`) और resumability। |

Sticky sessions और legacy हिस्से की कीमत का अपना अलग page है, **[legacy clients को serve करना](legacy-clients.md)**; दोनों पीढ़ियाँ खुद **[Protocol versions](../protocol-versions.md)** में हैं। यहाँ मायने रखता है जवाब का आकार: **2026-07-28 पर आप पहले से stateless हैं, configure करने को कुछ नहीं।**

इस page का बाकी हिस्सा उन दो चीज़ों के बारे में है जो stateless होने से आपको **नहीं** मिलतीं।

## अलग-अलग workers के बीच `requestState` {#requeststate-across-workers}

**[multi-round-trip](../handlers/multi-round-trip.md)** tool को कुछ ऐसा चाहिए होता है जो client को जाकर लाना पड़ता है (एक confirmation, एक चुनाव, एक credential), इसलिए वह जवाब की जगह सवाल लौटाता है और retry पर काम पूरा करता है। दोनों rounds के बीच client के पास एक opaque `request_state` token होता है जिसे server ने बनाया था। retry पर server को वह token फिर से खोलना होता है।

**किस key से seal किया गया?** default रूप से, उस key से जो server ने construction के समय `os.urandom(32)` से बनाई थी। `--workers 4` में यह चार constructions हैं, चार processes में: चार अलग-अलग keys, कहीं लिखी नहीं गईं, कभी साझा नहीं हुईं, restart पर गायब।

यह रहा एक tool जो कुछ करने से पहले पूछता है, ऐसे server पर जो कुछ भी configure नहीं करता:

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

पहला round worker A तक पहुँचता है। worker A `refund:120` को **अपनी** key से seal करता है और token लौटाता है। client सवाल किसी इंसान के सामने रखता है, हाँ पाता है, और retry करता है। यह retry बिल्कुल नई HTTP request है।

!!! check
    मान लें वह retry worker B तक पहुँचती है। B ऐसे token को unseal करने की कोशिश करता है जो उसने नहीं बनाया, कर नहीं पाता, और
    पूरा round ठुकरा देता है। `refund` कभी call नहीं होता; client को JSON-RPC error मिलता है:

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    यह message **कभी नहीं बदलता**। Expired हो, छेड़छाड़ हुई हो, अलग arguments के साथ replay किया गया हो, या
    (असली deployment में सबसे आम कारण) किसी सहोदर worker ने seal किया हो: client को
    हर बार यही बताया जाता है, इसलिए wire पर कभी पता नहीं चलता कि कौन-सी जाँच fail हुई। असली कारण
    server के log में एक `WARNING` है:

    ```text
    requestState rejected on tools/call: unknown key
    ```

    जो multi-round-trip tool एक worker पर चलता था और दो पर **कभी-कभी** fail होने लगा,
    उसकी वजह यही है। दोनों rounds को अब भी एक ही process तक पहुँचना होता है, इसलिए यह ठीक उतनी बार fail होता है जितनी बार
    आपका load balancer उन्हें अलग कर देता है।

दोनों rounds दो स्वतंत्र HTTP requests हैं, और कई आम चीज़ें उन्हें अलग कर देती हैं: हर request पर balance करने वाला proxy, बीच में टूट गया connection, कोई deploy या restart, ऐसा client जिसने `request_state` सहेज रखा था और अब बिल्कुल अलग process से resume कर रहा है (**[Loop खुद चलाना](../handlers/multi-round-trip.md#driving-the-loop-yourself)**)। इनमें से कोई भी "एक अलग worker" है।

इलाज एक argument है। उसके **दो** हिस्से हैं।

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** वह हिस्सा है जो सबको मिल जाता है। हर instance को एक ही secret दें (कम से कम 32 bytes का), और हर instance वह unseal कर सकता है जो किसी भी सहोदर ने बनाया। `keys[0]` seal करती है और सूची की हर key unseal करती है, यही rotation ring है; इसे बिना downtime के कैसे घुमाएँ, यह **[Keys rotate करना](../handlers/multi-round-trip.md#rotating-keys)** में है।
* **server का नाम** वह हिस्सा है जो लगभग किसी को नहीं मिलता, और यही कारण है कि key साझा करने के बाद भी cross-instance retries fail होती रहती हैं। हर sealed token में server का `name` एक **audience claim** के रूप में होता है, जिसे वापसी पर सख़्ती से जाँचा जाता है। एक ही code से बने दो instances का नाम एक ही होता है और उन्हें इसका कभी पता भी नहीं चलता। उन्हें अलग-अलग नाम दें (`MCPServer(f"billing-{POD}")` अच्छी observability आदत जैसा लगता है), और हर cross-instance retry ठीक ऊपर की तरह ठुकरा दी जाती है, key साझा हो या न हो। log में `unknown key` की जगह `audience` लिखा आता है; client को फ़र्क़ पता नहीं चलता।

secret एक बार बनाएँ और वही value हर instance को दें। अगर आप 32 bytes से कम देते हैं तो SDK का अपना error message यही command चलाने को कहता है:

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "वही keys, **और** वही नाम"
    multi-instance deployment को दोनों साझा करने ही होंगे। अगर हर instance का अलग नाम आपके लिए ज़रूरी है,
    तो इसके बजाय पूरे fleet को एक स्पष्ट audience दें: `RequestStateSecurity(keys=[...], audience="billing")`।
    फिर हर instance `"billing"` के तहत बनाता और स्वीकार करता है, चाहे उसका नाम कुछ भी हो।

seal के बारे में बाकी सब कुछ **[`requestState` की सुरक्षा](../handlers/multi-round-trip.md#protecting-requeststate)** में है: यह क्या-क्या bind करता है, हर round का `ttl` (default रूप से 600 seconds), अपना codec लाना, और बिना configure किया default `stdio` पर बिल्कुल सही क्यों है। इस page का पूरा योगदान दो बातों की checklist है: **वही keys, वही नाम।**

!!! info
    भले ही आपने कभी `InputRequiredResult` न लिखा हो, आप इसी path पर हैं। जिस tool के parameters
    `Resolve(...)` इस्तेमाल करते हैं (**[Dependencies](../handlers/dependencies.md)**) वह multi-round-trip tool है,
    और SDK उसके लिए उसका `request_state` बनाता और seal करता है। वही default key, workers के बीच वही
    failure, वही इलाज।

## अलग-अलग replicas के बीच change notifications {#change-notifications-across-replicas}

client की `subscriptions/listen` stream एक लंबे समय तक चलने वाला response है, इसलिए वह अपनी पूरी ज़िंदगी एक replica से बँधी रहती है। किसी **दूसरे** replica पर publish हुआ `ctx.notify_resource_updated(...)` उस तक पहुँचना चाहिए।

दोनों के बीच का जोड़ `SubscriptionBus` है। आप server को जो भी bus देते हैं, हर publish उसी में जाता है और हर खुली stream उसी को सुनती है, इसलिए हर replica को वही bus दें:

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

fan-out को इससे कोई मतलब नहीं कि stream किस server object से जुड़ी है। एक ही `InMemorySubscriptionBus` रखने वाले दो servers पहले से ऐसे ही बर्ताव करते हैं: एक पर listen stream खोलें, दूसरे पर `edit_note` चलाएँ, और stream को इसकी ख़बर मिल जाती है। वह in-memory bus सिर्फ़ एक process के अंदर के server objects तक फैलता है, इसलिए यह model है, deployment नहीं:

* असली processes के बीच, **SDK में ऐसा कोई bus नहीं आता जो आपकी मदद कर सके।** `SubscriptionBus` दो methods वाला `Protocol` है (`publish` और `subscribe`) जिसे आप अपने pub/sub backend (Redis, NATS, जो भी आप पहले से चलाते हैं) के ऊपर implement करते हैं और `MCPServer(subscriptions=...)` के रूप में देते हैं। sketch और contract **[Subscriptions](../handlers/subscriptions.md#scaling-past-one-process)** में हैं।
* bus चार छोटे typed events ढोता है, JSON-RPC कभी नहीं। Acknowledgment, filtering, और stream lifecycle SDK में ही रहते हैं, इसलिए आपका bus protocol तोड़ नहीं सकता; वह सिर्फ़ events को processes के बीच ले जा सकता है।
* Streams resumable **नहीं** हैं और events replay **नहीं** होते। कोई replica खो जाए तो उसकी streams गिर जाती हैं; clients फिर से listen और फिर से fetch करते हैं। साझा करने को कोई event store नहीं और configure करने को और कुछ नहीं। यह वह एक जगह है जहाँ scale out करना सच में बस वही चीज़ और ज़्यादा है।

## SDK आपको क्या नहीं देता {#what-the-sdk-does-not-give-you}

`MCPServer` एक protocol implementation है, application server नहीं। जिन deployment knobs को आप आगे ढूँढने जाएँगे वे जान-बूझकर नहीं हैं:

* **कोई `workers=` नहीं।** `mcp.run("streamable-http")` ठीक एक uvicorn process शुरू करता है, और वह कभी बस इतना ही शुरू करेगा। Multi-process का मतलब है `streamable_http_app()` को उसी चीज़ को सौंपना जिससे आप पहले से ASGI deploy करते हैं: `uvicorn --workers`, gunicorn, आपके platform का process manager। यह page जान-बूझकर इनमें से किसी का tutorial नहीं है; उनका documentation यहाँ उसकी नकल से बेहतर है।
* **कोई health-check route नहीं।** `@mcp.custom_route("/health", methods=["GET"])` ही पूरा जवाब है, और इस पर कभी authentication नहीं लगता, तब भी नहीं जब बाकी server पर लगा हो। liveness probe के लिए यह सही है, किसी भी निजी चीज़ के लिए गलत। **[मौजूदा app में जोड़ना](asgi.md#custom-routes)** में एक उदाहरण है।
* **कोई production settings object नहीं।** `MCPServer` पर timeouts, TLS, graceful shutdown, या connection limits लिखने की कोई जगह नहीं है, क्योंकि इनमें से कोई भी उसका काम नहीं। ये आपके ASGI server के हैं, और आप उन्हें वहीं configure करते हैं। constructor जो गिनी-चुनी settings **लेता है**, वे **[अपना server चलाना](index.md)** में हैं।
* **कोई `EventStore` साथ नहीं आता, और 2026-07-28 पर उसका कोई काम भी नहीं।** Resumability legacy stateful हिस्से की feature है; modern exchange एक POST, एक response है, और resume करने को कुछ नहीं।

## सारांश {#recap}

* बिना कुछ configure किए app सिर्फ़ उन्हीं requests का जवाब देता है जो localhost को भेजी गई हों। `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` ही go-live gate है: जब तक आप इसे नहीं देते, असली hostname के पीछे हर request `421` है और कारण सिर्फ़ server के log में है।
* 2026-07-28 पर कोई session नहीं है और load balancer के sticky होने के लिए कुछ नहीं। `stateless_http=True` सिर्फ़ legacy का knob है क्योंकि modern request उस flag के पढ़े जाने से पहले ही route होकर जवाब पा लेती है।
* default `requestState` key `os.urandom(32)` है, हर process में अलग बनी हुई। कोई multi-round-trip retry जो दूसरे worker तक पहुँचे, `-32602` *"Invalid or expired requestState"* के साथ fail होती है।
* इलाज है `RequestStateSecurity(keys=[...])` **और** हर instance पर एक ही server नाम। नाम ही token का default audience claim है। वही keys, वही नाम।
* Change notifications एक साझा `SubscriptionBus` के ज़रिए replicas के पार जाते हैं। SDK का एकमात्र implementation in-process है; अपने pub/sub के ऊपर दो methods वाला `Protocol` आपको खुद लिखना है।
* कोई `workers=` नहीं, कोई health route नहीं, कोई production settings object नहीं। अपना ASGI server खुद लाएँ।

असली hostname के सामने जो दूसरी चीज़ चाहिए वह है token: **[Authorization](authorization.md)**।
