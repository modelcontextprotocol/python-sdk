---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# Extensions {#extensions}

**extension** एक identifier के पीछे रखा गया MCP behaviour का opt-in bundle है।

server पर यह tools, resources और नए request methods जोड़ सकता है, और `tools/call` को wrap कर सकता है। client पर यह `tools/call` के अतिरिक्त result shapes claim कर सकता है और vendor notifications observe कर सकता है। हर पक्ष अपने-अपने `capabilities.extensions` के तहत advertise करता है, और जिसने इसे नहीं माँगा उसके लिए कुछ नहीं बदलता। यही contract है ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)), और इसका एक सुनहरा नियम है: **extensions default रूप से बंद रहते हैं**।

## extension इस्तेमाल करना {#using-an-extension}

construction के समय instances पास करें:

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

हो गया। अब server `capabilities.extensions` के तहत `io.modelcontextprotocol/ui` advertise करता है और extension जो कुछ जोड़ता है वह सब serve करता है।

`Apps` built-in reference extension है, और इसका अपना अलग page है: **[MCP Apps](apps.md)**।

!!! note
    extensions construction के समय ही तय हो जाते हैं। बाद में call करने के लिए कोई `add_extension` नहीं है: जब clients server से जुड़े हों, तब उसका capability map बदलना नहीं चाहिए।

capability map `server/discover` के साथ जाता है, जो **2026-07-28** का रास्ता है। legacy `initialize` handshake में इसे रखने की कोई जगह नहीं है, इसलिए legacy client को extension दिखता ही नहीं। इसे ध्यान में रखकर design करें: extension server को **बढ़ाता** है, server को इस्तेमाल करने का यही एकमात्र तरीका नहीं होना चाहिए।

## अपना extension लिखना {#writing-your-own}

`Extension` को subclass करें और सिर्फ़ वही override करें जिसकी ज़रूरत हो। हर method का default है।

### Identifier {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

identifier एक `vendor-prefix/name` string है जो spec की `_meta` key grammar का पालन करती है: dot से अलग किए गए labels (हर label अक्षर से शुरू होता है, अक्षर या अंक पर खत्म होता है), फिर एक slash, फिर name। यह **class define होते ही** validate होता है, इसलिए typo पकड़ने के लिए server के boot होने का इंतज़ार नहीं करना पड़ता:

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

prefix के रूप में ऐसा domain इस्तेमाल करें जो आपके नियंत्रण में हो। `io.modelcontextprotocol/*` उन extensions के लिए है जिन्हें खुद MCP project specify करता है।

### tools जोड़ना {#contributing-tools}

सबसे छोटा काम का extension एक tool और एक settings map है:

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` `ToolBinding`s लौटाता है। server हर एक को ठीक वैसे ही register करता है जैसे आपने खुद `mcp.add_tool(...)` call किया हो: वही schema generation, वही `Context` injection, सब कुछ वही।
* `settings()` वह value है जो `capabilities.extensions["com.example/stamps"]` पर advertise होती है। बिना settings के extension advertise करने के लिए `{}` (default) लौटाएँ।
* extension को server कभी नहीं मिलता। यह अपने योगदान data के रूप में declare करता है; `MCPServer` उन्हें consume करता है। mutate करने के लिए कोई `self.server` नहीं है।

और `main()` इसका सबूत है, सीधे `mcp` से जुड़ा एक in-memory client:

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### अपने methods serve करना {#serving-your-own-methods}

extension **नए request methods** register कर सकता है: उसके अपने verbs, जो spec के verbs के साथ-साथ serve होते हैं:

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` `RequestParams` को subclass करता है, इसलिए 2026 का `_meta` envelope एक समान तरीके से parse होता है और आपके handler को validated params मिलते हैं, कच्चा dict कभी नहीं। जो client के नियंत्रण में है उसकी सीमा बाँधें: `Field(ge=1, le=100)` किसी बेतुके `limit` को तभी reject कर देता है, इससे पहले कि आपका code उसके लिए कुछ allocate करे।
* `require_client_extension(ctx, EXTENSION_ID)` ही gate है: जिस client ने extension declare नहीं किया उसे `-32021` (missing required client capability) error मिलता है, साथ में वह machine-readable `requiredCapabilities` payload जो spec माँगता है।
* `protocol_versions=frozenset({"2026-07-28"})` method को एक wire version पर pin कर देता है। किसी भी दूसरे version पर client को `METHOD_NOT_FOUND` मिलता है, ठीक वैसे जैसे method वहाँ मौजूद ही न हो। उस client के लिए, वह है भी नहीं।

methods **सख़्ती से additive** हैं। SDK इसे construction के समय लागू करता है, runtime पर नहीं:

* spec में define किए गए method (`tools/list`, `completion/complete`, ...) के लिए `MethodBinding` बनाते ही `ValueError` raise होता है। core verbs server के हैं।
* एक ही method को bind करने वाले दो extensions हों, तो दूसरा register होते ही raise होता है। plugins एक-दूसरे को last-write-wins से ही खराब करते हैं; हम ऐसा नहीं करते।
* खाली `protocol_versions` set भी raise करता है: जो method कभी serve ही नहीं हो सकता वह bug है, configuration नहीं।

### Client side {#the-client-side}

उसी file का `main()` ही client की पूरी कहानी है, उसके दोनों हिस्से:

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` extension declare करता है। ये declarations `ClientCapabilities.extensions` बन जाती हैं: 2026-07-28 connection पर यह map हर request के `_meta` envelope में जाता है, इसलिए server इसे **हर** request पर देखता है; legacy connection पर यह `initialize` handshake के साथ जाता है। server code को फ़र्क नहीं पड़ता कि कौन सा: `require_client_extension(ctx, ...)` और `ctx.session.check_client_capability(...)` दोनों रास्तों पर सही स्रोत पढ़ते हैं।
* vendor methods एक परत नीचे `client.session.send_request(...)` पर उतरते हैं; `Client` सिर्फ़ spec verbs के लिए first-class methods जोड़ता है। `send_request` कोई भी `Request` subclass स्वीकार करता है, इसलिए vendor request जैसी है वैसी ही चली जाती है।

### `tools/call` को intercept करना {#intercepting-toolscall}

यह इकलौता interceptive hook है। tool call को observe, short-circuit या veto करने के लिए `intercept_tool_call` override करें:

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` validated `CallToolRequestParams` है: आपको `params.name` और `params.arguments` बिना raw JSON छुए मिलते हैं। यही तय करता है कि कौन सा tool call चलेगा: `call_next` से rewritten context पास करने से वह बदलता है जो handler `ctx` पर देखता है, tool invocation नहीं। wire-level request rewriting [Middleware](middleware.md) का काम है।
* `call_next(ctx)` chain का बाकी हिस्सा चलाता है और handler का result लौटाता है। इसे बिना बदले लौटाएँ (observe), कुछ और लौटाएँ (replace), या `MCPError` raise करें (refuse)। आप जो भी लौटाते हैं वह किसी भी handler result की तरह serialize होता है, 2026 पीढ़ी के `serverInfo` identity stamp समेत, इसलिए short-circuit करने वाला interceptor कभी anonymous या off-schema response नहीं बनाता।
* कई extensions होने पर interceptors registration के क्रम में nest होते हैं: `extensions=[...]` में पहला extension सबसे बाहर होता है।
* default implementation pass-through है, और जिस server के extensions इस hook को कभी override नहीं करते, उसका bare `tools/call` handler अनछुआ रहता है। जो आप इस्तेमाल नहीं करते उसकी कीमत नहीं चुकाते।

hook `tools/call` को wrap करता है, और कुछ नहीं। हर message से जुड़ी बातों के लिए [Middleware](middleware.md) इस्तेमाल करें। वह इसी के लिए है।

## client extension इस्तेमाल करना {#using-a-client-extension}

**client extension** वही contract है, इस्तेमाल करने वाले पक्ष से: एक identifier के पीछे client-side behaviour का bundle। instances को `Client(extensions=[...])` में पास करें और tools सामान्य तरीके से call करें:

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` हर दूसरे call की तरह सादा `CallToolResult` लौटाता है। extension ने जो बदला: server अब `buy` का जवाब final result के बजाय `receipt` **result shape** से दे सकता है, और `call_tool` के लौटने से पहले `Receipts` उसे पूरा कर देता है (यहाँ follow-up call से receipt redeem करके)। call site में कुछ नहीं हिलता।

extension हटा दें तो इनमें से कुछ भी मौजूद नहीं: server का gate उस client को मना कर देता है जिसने इसे declare नहीं किया (error -32021), और gate छोड़ने वाले server से आया claimed shape validation में fail होता है, ठीक वैसे जैसे spec अनजान `resultType` के लिए माँगता है। default रूप से बंद, wire के दोनों सिरों पर।

**बिना** किसी client-side behaviour के identifier advertise करने के लिए (server capability पर gate लगाता है, client कुछ नहीं करता, जैसे ऊपर वाले search client में), `advertise()` इस्तेमाल करें:

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## client extension लिखना {#writing-a-client-extension}

`ClientExtension` को subclass करें और सिर्फ़ वही override करें जिसकी ज़रूरत हो। योगदान के तीन प्रकार, हर एक का default: `settings()`, `claims()` और `notifications()`।

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* identifier वही grammar मानता है जो server का, और class define होते ही validate होता है।
* `claims()` `ResultClaim`s लौटाता है: एक wire tag, उसे parse करने वाला model, और उसे पूरा करने वाला resolver। model के लिए `result_type: Literal["receipt"]` से tag pin करना ज़रूरी है और वह verb के core result types को subclass नहीं कर सकता; दोनों बातें claim बनते समय enforce होती हैं। `receipt_token` जैसे vendor fields wire पर जैसे हैं वैसे जाते हैं: substituted shape client तक हू-ब-हू पहुँचता है।
* resolver को parsed model और एक `ClaimContext` मिलता है; `ctx.session` वही public handle है जो `client.session`, इसलिए follow-ups साधारण session calls हैं। यह verb का सामान्य `CallToolResult` लौटाता है।
* `settings()` वह value है जो `ClientCapabilities.extensions[identifier]` पर advertise होती है, और `Client` बनते समय एक बार पढ़ी जाती है।

`notifications()` observe करने के लिए vendor server notifications declare करता है:

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

handler को validated params एक-एक करके, dispatch के क्रम में मिलते हैं। यह observe करता है; veto या reply नहीं कर सकता।

दो शांत नियम। claims सिर्फ़ 2026-07-28 connections पर सक्रिय रहते हैं, और capability advertisement उन्हीं के पीछे चलता है: legacy connection पर claims गायब हो जाते हैं और identifier भी उनके साथ advertisement से हट जाता है, इसलिए client कभी ऐसा extension advertise नहीं करता जिसके shapes वह खुद reject कर देता। और जब claimed shape resolver के बजाय आपको खुद चाहिए, तो `client.session.call_tool(..., allow_claimed=True)` call करें; उस flag के बिना, session-tier caller तक पहुँचने वाला claimed shape `UnexpectedClaimedResult` raise करता है।

### Extension verbs {#extension-verbs}

extension के अपने request methods को client-side registration की ज़रूरत नहीं। vendor request type `mcp.types.Request` को subclass करता है और `client.session.send_request` से जाता है, जैसा [अपने methods serve करना](#serving-your-own-methods) में है। एक बात और: जब किसी params key का `Mcp-Name` header में जाना ज़रूरी हो (tasks जैसे extension specs अपने verbs के लिए यह माँगते हैं), तो request type `name_param` declare करता है:

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

session हर send path पर `params["jobId"]` को `Mcp-Name` में mirror करता है, और value न होने पर ज़रूरी header चुपचाप छोड़ने के बजाय साफ़ तौर पर fail होता है।

## extension क्या नहीं कर सकता {#what-an-extension-cannot-do}

योगदान की surface जानबूझकर **बंद** रखी गई है। server पर: settings, tools, resources, methods, एक `tools/call` interceptor। client पर: settings, result claims, notification bindings। extension ये नहीं कर सकता:

* **host के अंदर पहुँचना।** यह data declare करता है; इसके पास server या client का कोई reference नहीं होता।
* **core behaviour बदलना।** spec methods और core result tags construction के समय reject हो जाते हैं (`initialize` को runner ने पूरी तरह reserve कर रखा है); core vocabulary से ढकी notification binding इसके बजाय warning के साथ चुप हो जाती है।
* **देर से register करना।** `MCPServer(...)` या `Client(...)` के लौटने के बाद extension set जैसा है वैसा ही रहता है।

अगर आप इन दीवारों से लड़ रहे हैं, तो आप extension नहीं लिख रहे। आप fork लिख रहे हैं। ये दीवारें ही feature हैं: `extensions=[Apps(), Stamps()]` पढ़ने वाला user **सब कुछ** जानता है जिसे ये दोनों छू सकते थे।
