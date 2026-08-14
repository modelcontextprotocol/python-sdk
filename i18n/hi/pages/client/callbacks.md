---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# Client callbacks {#client-callbacks}

MCP में लगभग हर request एक ही दिशा में जाती है: client से server की ओर।

server भी **client** से चीज़ें माँग सकता है: user से कोई सवाल पूछना, user के model से sampling करना, user के workspace folders की सूची लेना। इन requests का जवाब आप `Client(...)` को **callbacks** देकर देते हैं।

## पूछने वाला server {#a-server-that-asks}

यह एक ऐसा server है जिसका tool अपने आप पूरा नहीं हो सकता:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` **client को** `elicitation/create` request भेजता है और इंतज़ार करता है।
* जब तक कोई (form में कोई व्यक्ति, या आपका code) `name` नहीं देता, tool लौटता नहीं।

यह server वाला आधा हिस्सा है, और इसकी पूरी जानकारी **[Elicitation](../handlers/elicitation.md)** page में है। यह page wire का दूसरा सिरा है।

## Elicitation callback {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* elicitation callback का रूप `async (context, params) -> ElicitResult` है।
* `params.message` सवाल है। `params.requested_schema` उस जवाब का JSON Schema है जो server चाहता है। असली client इससे form बनाकर दिखाता है; यह वाला अपने आप भर देता है।
* आप `ElicitResult(action="accept", content={...})` लौटाते हैं, या `action="decline"`, या `action="cancel"`। इनके अलावा सिर्फ़ एक विकल्प है `ErrorData(...)`, जो request को ठुकरा देता है और पूरा call fail कर देता है।
* `context` एक `ClientRequestContext` है: चालू `session`, server का `request_id`, और उसके साथ लगाया गया कोई भी `meta`।

!!! tip
    `params` elicitation के दोनों modes का union है। यहाँ `params.mode` का मान `"form"` है; `"url"` request
    में schema की जगह `params.url` आता है। एक ही callback दोनों को संभालता है; `params.mode` पर branch करें।
    पूरा pattern **[Elicitation](../handlers/elicitation.md)** में दिखाया गया है।

### इसे आज़माएँ {#try-it}

`issue_card` call करें और दोनों सिरों को देखें।

आपके callback को server का सवाल मिलता है, पहले से parse किया हुआ:

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

वह जवाब देता है, tool के अंदर `ctx.elicit(...)` आगे बढ़ता है, और tool पूरा हो जाता है:

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

आपकी ओर से एक `tools/call`, server की ओर से वापस एक `elicitation/create`, जिसका जवाब आपके function ने दिया, और यह सब एक ही tool call के अंदर।

!!! info
    `Client(...)` call पर `mode="legacy"` असल में काम कर रहा है। default रूप से `Client(...)` modern
    protocol path negotiate करता है, और उस path में server-से-client requests के लिए कोई back-channel नहीं है:
    आपका callback चलने से पहले ही `ctx.elicit` fail हो जाता है। यह transport तय नहीं करता; negotiated
    protocol तय करता है, in-memory में भी और URL पर भी। जब भी आपके client को ऐसी किसी request का जवाब देना हो,
    `mode="legacy"` तय करें; इस page के पीछे का हर test यही करता है। पूरी जानकारी **[Protocol versions](../protocol-versions.md)** में है।

    2026-07-28 session पर callback बेकार नहीं होता, उसे input अलग तरीके से मिलता है: जब कोई tool
    `ElicitRequest` वाला `InputRequiredResult` लौटाता है, तो `Client` उस entry को उसी
    `elicitation_callback` को भेज देता है और आपके लिए call दोबारा करता है। वह flow **[Multi-round-trip requests](../handlers/multi-round-trip.md)** है।

## callback ही capability है {#a-callback-is-a-capability}

आपने server को कभी नहीं बताया कि आपका client elicitation requests का जवाब दे सकता है। SDK ने बताया।

जब client जुड़ता है तो वह अपनी `capabilities` घोषित करता है, जो server की capabilities का ठीक उल्टा रूप है। वह object आप नहीं लिखते। **callback register करना ही घोषणा है।**

| आप देते हैं | client घोषित करता है |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| इनमें से कोई नहीं | `{}` |

sampling की sub-capabilities ही एकमात्र बारीकी हैं: जब आपका sampler `tools` / `tool_choice` parameters संभालता हो, तो `sampling_callback` के साथ `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())` दें। servers को `sampling.tools` घोषित दिखनी चाहिए, तभी वे इन्हें भेज सकते हैं।

`logging_callback` और `message_handler` इस table में नहीं हैं। वे notifications संभालते हैं, और notifications को किसी capability की ज़रूरत नहीं।

server इस घोषणा को `ctx.session.check_client_capability(...)` से पढ़ता है। ऐसा करने वाला एक tool जोड़ें:

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

सिर्फ़ `elicitation_callback` के साथ जुड़ें और इसे call करें:

```python
result.structured_content  # {'result': ['elicitation']}
```

तीनों callbacks दें तो आपको `['elicitation', 'sampling', 'roots']` मिलता है। कोई न दें तो `[]` मिलता है।

!!! check
    अब गलत काम करें: `elicitation_callback` के **बिना** जुड़ें और फिर भी `issue_card` call करें।

    server की `elicitation/create` request फिर भी आपके client तक पहुँचती है, और SDK आपकी ओर से उसका
    जवाब देता है, error के साथ, क्योंकि आपने कभी कहा ही नहीं कि आप इसे संभाल सकते हैं। वह error पूरे call को
    डुबो देता है। `call_tool` कोई `is_error` result नहीं लौटाता; वह raise करता है:

    ```text
    MCPError: Elicitation not supported
    ```

    यह protocol error है (`-32600`, **invalid request**), tool error नहीं: model के पढ़ने और दोबारा
    कोशिश करने के लिए इसमें कुछ नहीं है। इसीलिए `client_features` रखना फ़ायदेमंद है: अच्छे ढंग से बना server
    पूछने से पहले जाँच लेता है।

## Deprecated जोड़ी {#the-deprecated-pair}

`sampling_callback` `sampling/createMessage` का जवाब देता है: server **आपके** model से कुछ complete करने को कहता है। `list_roots_callback` `roots/list` का जवाब देता है: server पूछता है कि वह किन directories में काम कर सकता है।

दोनों काम करते हैं। दोनों ऊपर वाले नियम का पालन करते हैं। और दोनों ऐसे RPCs को serve करते हैं जिन्हें **2026-07-28 spec हटा देता है**: modern server request के बीच में आपके client को वापस call नहीं करता, वह request को tool result के हिस्से के रूप में आपको वापस सौंप देता है (**[Multi-round-trip requests](../handlers/multi-round-trip.md)**)। callbacks खुद बेकार नहीं हुए हैं। जब किसी `InputRequiredResult` में `CreateMessageRequest` या `ListRootsRequest` होता है, तो `Client` का auto-loop उसे उसी `sampling_callback` या `list_roots_callback` को भेज देता है जो आपने यहाँ register किया था। पूरी सूची **[Deprecated features](../deprecated.md)** में है।

जो servers अभी आगे नहीं बढ़े हैं, उनसे बात करने के लिए आपको ये callbacks अब भी चाहिए। signatures:

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* sampling callback को पूरा `CreateMessageRequestParams` (`messages`, `model_preferences`, `max_tokens`) मिलता है और वह `CreateMessageResult` लौटाता है। model **आप** चलाते हैं, जैसे चाहें; SDK सिर्फ़ request पहुँचाता है।
* roots callback कोई params नहीं लेता और `ListRootsResult` लौटाता है।
* दोनों में से कोई भी, मना करने के लिए, इसकी जगह `ErrorData(...)` लौटा सकता है।

इन्हें `Client(...)` को ठीक वैसे ही दें जैसे `elicitation_callback` को।

## Notification callbacks {#the-notification-callbacks}

दो और। इनमें से कोई कुछ घोषित नहीं करता।

`logging_callback` को server की भेजी हुई `notifications/message` मिलती है, `LoggingMessageNotificationParams` (`level`, `logger`, `data`) के रूप में। protocol logging खुद 2026-07-28 spec में deprecated है (इसकी जगह क्या करना है, यह **[Logging](../handlers/logging.md)** में है), इसलिए यह callback उन servers के लिए है जो इसे अब भी emit करते हैं। 2026 पीढ़ी के connection पर अकेला callback आपको कुछ नहीं दिलाता, क्योंकि 2026 servers log messages सिर्फ़ उन्हीं requests को भेजते हैं जो इसके लिए opt in करती हैं: हर request पर वह opt-in लगाने और उस level व उससे ऊपर के messages पाने के लिए `Client(...)` को `log_level="info"` (या कोई और level) दें। 2026 से पहले के servers इसे नज़रअंदाज़ करते हैं और अपना `logging/setLevel` वाला व्यवहार बनाए रखते हैं।

`message_handler` सब कुछ पकड़ने वाला है: session जो भी server notification सामने लाता है, वह इस तक पहुँचती है (उसके खास callback के अलावा), और stream-backed transport पर हर transport-level `Exception` भी। दो कभी नहीं पहुँचते: `notifications/cancelled` को SDK सामने लाने के बजाय खुद लागू करता है, और चालू `listen()` stream की subscription acknowledgment उसी stream में खप जाती है। parameter को `IncomingMessage` (`ServerNotification | Exception`, `mcp.client` से export किया हुआ) से annotate करें। जानने लायक एक ही pattern है `if isinstance(message, Exception): raise message`, ताकि टूटा हुआ connection चुपचाप गायब होने के बजाय ज़ोर से fail हो।

## सारांश {#recap}

* server client को requests भेज सकता है। आप उनका जवाब `Client(...)` को दिए गए callbacks से देते हैं।
* elicitation callback मौजूदा वाला है: `async (context, params) -> ElicitResult`, form और URL mode दोनों के लिए एक ही function।
* **callback register करना ही capability घोषित करना है।** इसके बिना SDK आपकी ओर से server की request ठुकरा देता है और पूरा call `MCPError` के साथ fail हो जाता है।
* server पूछने से पहले `ctx.session.check_client_capability(...)` से पता कर लेता है।
* `sampling_callback` और `list_roots_callback` इसी तरह काम करते हैं लेकिन deprecated features को serve करते हैं; modern servers इनकी जगह multi-round-trip requests इस्तेमाल करते हैं।
* `logging_callback` और `message_handler` को notifications मिलती हैं। वे कुछ घोषित नहीं करते।

`Client(...)` का पहला argument transport object है। हर प्रकार की जानकारी **[Client transports](transports.md)** में है।
