---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# Multi-round-trip requests {#multi-round-trip-requests}

कभी-कभी कोई tool एक round trip में पूरा नहीं हो पाता। उसे कुछ ऐसा चाहिए जो सिर्फ़ user के पास है: कोई चुनाव, कोई पुष्टि, कोई credential।

2026-07-28 से पहले server यह चीज़ **वापस call करके** लेता था: मूल request को संभालने के बीच में ही client की तरफ़ अपनी request खोलकर (कोई elicitation, कोई sampling call)। 2026-07-28 spec उस back-channel को बंद कर देता है।

इसके बजाय, server **लौटाता** है।

## लौटाएँ, वापस call न करें {#return-dont-call-back}

server `tools/call` का जवाब `CallToolResult` की जगह **`InputRequiredResult`** से देता है। इसके दो fields सारा काम करते हैं:

* **`input_requests`**: server को अभी और क्या चाहिए, एक dict के रूप में जिसकी keys server ने खुद चुनी हैं। हर value एक `ElicitRequest`, `CreateMessageRequest`, या `ListRootsRequest` है।
* **`request_state`**: एक opaque token। client retry पर इसे ज्यों का त्यों वापस भेजता है। इसे पढ़ने वाला सिर्फ़ server है।

client हर request पूरी करता है, फिर **उसी tool को दोबारा** call करता है, अपने जवाब `input_responses` में और token `request_state` में लेकर। अब server के पास वह है जो पहले नहीं था, और वह सामान्य `CallToolResult` लौटाता है।

पूरा protocol बस इतना ही है। हर चरण client से server की ओर जाने वाली साधारण request है। उल्टी दिशा में कभी कुछ नहीं बहता।

## server की तरफ़ {#the-server-side}

`@mcp.tool()` पर आप इसे शायद ही कभी हाथ से बनाते हैं: ऐसी dependency घोषित करें जो user से पूछती है (`Elicit`), client के LLM से sample लेती है (`Sample`), या उसके roots की सूची लेती है (`ListRoots`), और SDK आपके लिए `InputRequiredResult` लौटा देता है; वह रूप **[Dependencies](dependencies.md)** page पर है। दोनों रूप आपस में नहीं मिलते: एक call के पास `input_responses`/`request_state` का एक ही channel होता है, इसलिए `Resolve(...)` parameters इस्तेमाल करने वाला tool अपनी body से `InputRequiredResult` भी नहीं लौटा सकता। घोषित `InputRequiredResult` return registration के समय ही अस्वीकार हो जाता है (`InvalidSignature`), और बिना घोषित वाला runtime पर call को fail कर देता है। हाथ से बनाने वाला रूप **low-level** `Server` है, जिसके `on_call_tool` handler को दोनों में से कोई भी result type लौटाने की अनुमति है:

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` का type `-> CallToolResult | InputRequiredResult` है। दूसरा वाला लौटाना ही server की तरफ़ का पूरा API है।
* पहली call पर `params.input_responses` `None` है, इसलिए guard चलता है और handler जवाब देने के बजाय पूछता है।
* retry पर, client का भेजा `ElicitResult` **उसी key** (`"region"`) के नीचे रखा मिलता है जो server ने `input_requests` में इस्तेमाल की थी।

उस file का बाकी सब कुछ (स्पष्ट `input_schema`, हाथ से बना `CallToolResult`) साधारण low-level `Server` है, जो **[Low-level Server](../advanced/low-level-server.md)** में बताया गया है। यह page सिर्फ़ दूसरा return type जोड़ता है।

## tools से आगे {#beyond-tools}

`tools/call` में कुछ खास नहीं है: 2026-07-28 पर server `prompts/get` और `resources/read` का जवाब भी इसी तरह दे सकता है। `MCPServer` पर, `@mcp.prompt()` function — या `@mcp.resource()` **template** function — खुद `InputRequiredResult` लौटाता है और retry के जवाब context से पढ़ता है:

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* पहला round `InputRequiredResult` लौटाता है। retry पर, `ctx.input_responses` में वही keys के नीचे जवाब होते हैं और function अपना साधारण result लौटाता है — यहाँ prompt messages, template resource के लिए resource content।
* आपका set किया `request_state` wire पार करने से पहले seal होता है और echo पर verify होता है, server पर बाकी सब की तरह; नीचे **[`requestState` की सुरक्षा](#protecting-requeststate)** बताता है कि seal आपको क्या देता है और keys कब configure करनी होती हैं।
* जब dependency वाला रूप फिट न बैठे, तो `@mcp.tool()` function भी इसी तरह सीधे result लौटा सकता है।
* static `@mcp.resource()` functions इसमें हिस्सा नहीं लेते: वे `Context` नहीं लेते, इसलिए retry कभी पढ़ ही नहीं सकते। सिर्फ़ template resources पूछ सकते हैं।
* नीचे दिए पीढ़ी के नियम बिना बदलाव लागू होते हैं: pre-2026 session पर `InputRequiredResult` लौटाना वही `-32603` है जिसका ज़िक्र warning में है।

## client की तरफ़ {#the-client-side}

`Client` आपके लिए loop चलाता है।

वे callbacks register करें जो server माँग सकता है (`elicitation_callback`, `sampling_callback`, `list_roots_callback`) और tool call करें। जब `InputRequiredResult` आता है, `Client` `input_requests` की हर entry को मेल खाते callback के पास भेजता है, जवाबों और echo किए `request_state` के साथ retry करता है, और तब तक चलता रहता है जब तक `CallToolResult` वापस न आ जाए:

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* वह `elicitation_callback` वही है जिस पर pre-2026 server का back-channel `elicitation/create` पहुँचता। `sampling/createMessage` के लिए `sampling_callback` और `roots/list` के लिए `list_roots_callback` पर भी यही बात लागू है: 2026-07-28 पर अलग से चलने वाले server->client RPC चले गए हैं, लेकिन हूबहू वही `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` payloads `input_requests` के अंदर आते हैं और उन्हीं तीन callbacks तक पहुँचते हैं। callbacks का एक ही set दोनों पीढ़ियों को serve करता है।
* `call_tool` सादा `CallToolResult` लौटाता है। बीच के rounds caller को नहीं दिखते।
* `get_prompt` और `read_resource` भी यही loop चलाते हैं।

!!! check
    callback न लगाएँ तो loop पहले ही round में fail हो जाता है: SDK का stand-in callback
    हर elicitation का जवाब error से देता है, और `call_tool` *"Elicitation not supported"*
    message के साथ `MCPError` raise करता है।

loop की सीमा है। `Client(..., input_required_max_rounds=10)` default cap है; जो server उससे आगे भी `InputRequiredResult` लौटाता रहे, वह `call_tool` से raise करवा देता है। अगर किसी round में सिर्फ़ `request_state` हो और कोई `input_requests` न हो, तो `Client` retry करने से पहले थोड़ी देर sleep करता है (50ms से दोगुना होते हुए 250ms की सीमा तक), ताकि जो server बस *"अभी पूरा नहीं हुआ"* कह रहा है उसे लगातार poll न किया जाए।

### loop खुद चलाना {#driving-the-loop-yourself}

एक ही process वाले client के लिए auto-loop काफ़ी है। loop खुद तब संभालें जब:

* आपका client **distributed** है: जो process user को सवाल दिखाता है, वह वही process नहीं है जिसने `call_tool` call किया था, इसलिए retry कोई दूसरा worker भेजता है। `request_state` वह सहेजा जा सकने वाला token है जिसे आप अपने storage के ज़रिए उस सीमा के पार ले जाते हैं, और `input_responses` वह है जो दूसरी तरफ़ से उसके साथ वापस आता है।
* आप हर round को **जाँचना** चाहते हैं: `input_requests` की हर entry को log या audit करना, कुछ तरह की requests को मना करना, या चरणों के बीच अपना backoff लगाना।
* आपको round की गिनती के बजाय **घड़ी के समय** की सीमा चाहिए: `input_required_max_rounds` पर निर्भर रहने के बजाय अपने loop को `anyio.fail_after(...)` में लपेटें।

नीचे के session पर उतरें, जहाँ `allow_input_required=True` आपको सीधे union देता है:

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` return type को `CallToolResult | InputRequiredResult` तक चौड़ा कर देता है। `isinstance` ही उसे वापस संकरा करता है।
* `request_state` अब आपके हाथ में है। चरणों के बीच इसे लिखकर रख लें तो बातचीत किसी नए process से फिर शुरू हो सकती है।
* `input_requests` की हर entry के लिए आप `input_responses` में **उसी key** के नीचे एक `InputResponse` रखते हैं। `fulfil` वह जगह है जहाँ आपका UI आता है; यह वाला जवाब hard-code करता है।
* हर चरण में वही tool name, वही `arguments`। retry मूल call को दोबारा पूरा करना है, कोई नया method नहीं।

## `requestState` की सुरक्षा {#protecting-requeststate}

ऊपर सब कुछ `request_state` को echo मानता है, और wire पर वह बस इतना ही है। लेकिन client इसे चरणों के बीच अपने पास रखता है (processes के पार इसे लिखकर रखना ही वह चीज़ है जिसकी पिछले section ने अनुमति दी), इसलिए जो वापस आता है वह **client का दिया input** है: उसमें बदलाव हो सकता है, वह expire हो सकता है, या किसी बिल्कुल अलग call से उठाया गया हो सकता है। spec की माँग है कि जब भी यह state authorization, resource access, या business logic पर असर डाल सकता हो, servers इस state की integrity सुरक्षित रखें और verification fail होने पर round को अस्वीकार करें।

`MCPServer` default रूप से इसकी सुरक्षा करता है। हर server बाहर जाने वाले `requestState` को seal करता है और हर echo को verify करता है — resolver state और हाथ से बना state, दोनों — process शुरू होने पर बनी key के तहत। आपको कुछ configure नहीं करना, plaintext लिखना है और plaintext पढ़ना है; wire पर सिर्फ़ एक opaque encrypted token जाता है।

default key process के साथ ही जीती-मरती है, और एक process से आगे deploy करने से पहले यही एक बात आपको पता होनी चाहिए:

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **default (बिना configuration)** एक process के लिए ठीक है: stdio, या ठीक एक HTTP worker। जो retry किसी दूसरे worker पर, load balancer के पीछे किसी दूसरे instance पर, या restart के बाद उसी server पर पहुँचती है, वह ऐसी key के तहत seal हुई होती है जो उस process के पास नहीं है — client को नीचे वाला तय rejection मिलता है और उसे flow फिर से शुरू करना पड़ता है।
* **`keys=[...]`** तब ज़रूरी है जब भी retry किसी **दूसरे instance** तक पहुँच सकती हो (multi-worker `uvicorn`, load-balanced HTTP) या restarts के पार बचनी हो: हर instance वह verify करता है जो किसी भी sibling ने mint किया। वही मशीनरी, बनाई गई key की जगह आपका secret।
* अपनी crypto के लिए, जैसे कोई KMS या मौजूदा token service, `keys` की जगह `RequestStateSecurity(codec=...)` दें; नीचे **[अपनी crypto लाएँ](#bring-your-own-crypto)** contract बताता है।

### seal में क्या होता है {#what-the-seal-carries}

default हो या configured, wire पर `requestState` एक encrypted, authenticated token है। आपका code इसे कभी नहीं देखता: handlers और resolvers plaintext लिखते हैं और plaintext पढ़ते हैं (`ctx.request_state`); SDK बाहर जाते समय seal करता है और अंदर आते समय verify करता है। integrity के अलावा, हर token इनसे बँधा होता है:

* **एक समय सीमा।** हर round नई expiry के साथ दोबारा seal करता है, इसलिए `RequestStateSecurity(ttl=...)` (default 600 seconds) हर round के सोचने के समय को बाँधता है, पूरे flow को नहीं।
* **authenticated principal।** जब request में ऐसा OAuth access token हो जिसे SDK ने validate किया, तो state उस token के client, issuer, और subject से बँध जाता है: एक user के लिए mint हुआ state दूसरे user के तहत fail होता है, भले ही दोनों users एक ही OAuth client साझा करते हों। जो verifier कोई subject नहीं देता, उसके साथ binding घटकर सिर्फ़ client identity तक रह जाती है, जो URL-आधारित client IDs में उस client software के हर user के बीच साझा होती है। जब auth SDK के बाहर खत्म होता है (आगे लगा proxy), या transport unauthenticated है, तो बाँधने के लिए कोई principal नहीं होता और यह जाँच निष्क्रिय रहती है, जब तक `RequestStateSecurity(bind_principal=...)` आपके अपने identity signal से कोई principal न दे। आपका token verifier जो भी components देता है, उन्हें लगातार एक जैसे देना चाहिए: जो verifier कुछ requests पर subject शामिल करे और दूसरों पर छोड़ दे, वह flow के बीच में principal बदल देता है, और चल रहे rounds अस्वीकार हो जाते हैं।
* **मूल request।** method, tool या prompt का नाम (या resource URI), और arguments का digest। किसी दूसरे tool, दूसरे arguments, या दूसरे method के विरुद्ध replay किया token fail होता है।
* **पूछा गया ठीक वही सवाल।** हर resolver जवाब उस rendered सवाल से जुड़ा होता है जो client को दिखाया गया था, उस round पर भी जब वह पहली बार आता है और तब भी जब दर्ज किया जवाब बाद में दोबारा इस्तेमाल होता है। बदले हुए शब्दों वाले message या बदले schema के साथ redeploy करें तो server बासी जवाब खाने के बजाय दोबारा पूछता है। यही जुड़ाव दूसरी दिशा में भी असर करता है: messages tool के arguments से बनाएँ, हर call के data से नहीं। timestamp या live rate से बना message हर round में अलग render होता है, इसलिए हर दर्ज जवाब बासी दिखता है और server तब तक दोबारा पूछता रहता है जब तक client की round सीमा call को खत्म न कर दे।

यह सब SDK का काम है, आपका नहीं, और अगर आप अपना codec लाते हैं तो codec का भी नहीं।

### keys बदलना (rotation) {#rotating-keys}

`keys[0]` नया state seal करती है; सूची की हर key verify करती है। zero-downtime rotation तीन चरणों में होता है, हर चरण अगले से पहले पूरी तरह roll out:

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

minter को कभी पहले promote न करें: ऐसी key के तहत mint करना जिसे कोई instance अभी verify नहीं कर सकता, rollout के बीच में चल रहे rounds गिरा देता है।

keys एक service तक सीमित हैं। sealed envelope में server का नाम audience claim के रूप में भी होता है, इसलिए किसी दूसरी service का mint किया token, जो संयोग से वही secret साझा करती हो, वैसे भी अस्वीकार हो जाता है। claim उतना ही विशिष्ट है जितना नाम, इसलिए जिस server को स्पष्ट policy दी गई हो उसका असली नाम होना चाहिए या उसे `RequestStateSecurity(audience=...)` set करना चाहिए — बिना नाम वाला construction पर ही raise करता है। `audience=` जान-बूझकर बनाई multi-service topologies के भी काम आता है जहाँ एक service को दूसरी का mint किया state स्वीकार करना हो। (बिना configuration वाला default इससे मुक्त है: उसकी key कभी process से बाहर नहीं जाती, इसलिए audience claim के पास जोड़ने को कुछ नहीं है।)

### अपनी crypto लाएँ {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` ऐसी कोई भी चीज़ लेता है जिसमें `seal(bytes) -> str` और `unseal(str) -> bytes` हों और जो हर उस token के लिए `InvalidRequestState` raise करे जो उसने mint नहीं किया। इसका classic रूप KMS के विरुद्ध envelope encryption है, जहाँ आप startup पर एक बार data key unwrap करते हैं और हर token की crypto local रखते हैं:

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL, principal binding, और request binding codec का काम **नहीं** हैं: SDK हर codec के लिए इन्हें `seal` से पहले payload में डालता है और `unseal` के बाद दोबारा verify करता है। codec की ज़िम्मेदारियाँ सिर्फ़ integrity (छेड़छाड़ का मतलब raise) और, आदर्श रूप से, confidentiality हैं।

### जब verification fail हो {#when-verification-fails}

हर inbound failure, चाहे छेड़छाड़ हुई हो, expire हुआ हो, किसी दूसरी request या principal के विरुद्ध replay हुआ हो, या ऐसी key के तहत seal हुआ हो जिसे यह server नहीं जानता, एक ही जवाब पाता है:

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

हर कारण के लिए एक ही तय message, ताकि wire कभी न बताए कि कौन सी जाँच fail हुई; असली कारण server log में जाता है। `tools/call`, `prompts/get`, और `resources/read` पर हर inbound `requestState` जाँचा जाता है, वह भी जो ऐसे handler के लिए आए जो कभी state mint नहीं करता। व्यवहार में सबसे आम rejection कोई हमलावर नहीं है — यह default process-local key का restart से पहले वाली या किसी दूसरे instance की retry से टकराना है; client flow फिर शुरू करता है, और जब यह मायने रखता हो तो `keys=[...]` ही उपाय है।

### हाथ से बना state {#hand-built-state}

जो `request_state` आप खुद set करते हैं (tool, prompt, या resource-template function से `InputRequiredResult` लौटाकर), वह उसी मशीनरी से seal और verify होता है जिससे resolver state, code में एक भी बदलाव के बिना: plaintext लिखें, plaintext पढ़ें, और ऊपर की हर binding लागू होती है।

एक चीज़ जो SDK आपके लिए तय नहीं कर सकता, configured होने पर भी, वह है सवाल की पहचान: उसे नहीं पता कि आपके state में कोई जवाब **आपके** किस सवाल का है। अगर आप जवाब सवाल की key से store करते हैं, तो state में अपना सवाल-identifier शामिल करें और retry पर उसे जाँचें।

low-level `Server` बिना-batteries वाला स्तर है: `MCPServer` के विपरीत, जब तक आप boundary खुद न जोड़ें तब तक कुछ seal नहीं होता, और ऐसा करने तक आपका `request_state` ठीक वैसे ही wire पार करता है जैसा लिखा गया। एक line वाला opt-in **[Low-level Server](../advanced/low-level-server.md#the-other-handlers)** में दिखाया गया है।

## एक 2026-07-28 result {#a-2026-07-28-result}

`InputRequiredResult` सिर्फ़ protocol version **2026-07-28** पर मौजूद है। in-memory `Client(server)` इसे आपके लिए negotiate करता है; wire पर, `mode="auto"` इसे खोज लेता है। connect करने के बाद `client.protocol_version` बताता है कि आपको क्या मिला।

!!! warning
    pre-2026 session के पास `InputRequiredResult` रखने की कोई जगह नहीं है। `mode="legacy"` connection पर
    अपने handler से इसे लौटाएँ तो runner इसे negotiate हुए version में serialize नहीं कर पाता; client
    को `-32603` *"Handler returned an invalid result"* error वापस मिलता है। जो server दोनों पीढ़ियों को
    serve करता है, उसे इसका सहारा लेने से पहले `ctx.protocol_version` जाँचना होगा।

!!! info
    **URL-mode elicitation** 2026 connection पर ठीक इसी mechanism पर चलता है। `input_requests`
    की entry ऐसी `ElicitRequest` है जिसके params `ElicitRequestURLParams` हैं; user out-of-band
    flow पूरा करता है और आपका client call retry करता है। वही loop, कोई नया API नहीं। high-level
    server वाला हिस्सा **[Elicitation](elicitation.md)** में है।

## सारांश {#recap}

* 2026-07-28 पर जिस server को call के बीच input चाहिए, वह `InputRequiredResult` **लौटाता** है। वह client की तरफ़ कभी request नहीं खोलता।
* `input_requests` वह है जो उसे चाहिए। `request_state` एक opaque resume token है जिसे सिर्फ़ server पढ़ता है।
* `Client` आपके लिए retry loop चलाता है: `elicitation_callback` / `sampling_callback` / `list_roots_callback` register करें और `call_tool` सादा `CallToolResult` लौटाता है। `input_required_max_rounds` (default 10) इसकी सीमा है।
* rounds जाँचने या सहेजने के लिए `client.session.call_tool(..., allow_input_required=True)` इस्तेमाल करें और `while isinstance(result, InputRequiredResult)` loop खुद संभालें।
* `@mcp.tool()` पर, user से पूछने वाली dependency यह result आपके लिए बनाती है (**[Dependencies](dependencies.md)**); **low-level** `Server` हाथ से बनाने वाला रूप है।
* prompts और resources भी हिस्सा लेते हैं: `@mcp.prompt()` या template `@mcp.resource()` function खुद `InputRequiredResult` लौटाता है और retry पर `ctx.input_responses` पढ़ता है।
* `requestState` client के दिए input के रूप में वापस आता है, इसलिए `MCPServer` इसे default रूप से seal करता है — resolver state और हाथ से बना state, दोनों — process-local key के तहत; multi-instance deployments `RequestStateSecurity(keys=[...])` (या custom codec) देते हैं ताकि हर instance वह verify कर सके जो किसी sibling ने mint किया। seal हर token को एक समय सीमा, मूल request, और authenticated principal से बाँधता है, जब request में SDK का validate किया auth हो या `bind_principal=` आपका अपना identity signal दे (**[`requestState` की सुरक्षा](#protecting-requeststate)**)।

यही वह mechanism है जो server-initiated sampling और push-शैली के बाकी back-channel की जगह लेता है; **[Deprecated features](../deprecated.md)** देखें।
