---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# Dependencies {#dependencies}

tool के arguments model से आते हैं। कुछ values कभी वहाँ से नहीं आनी चाहिए: आपके records से निकाली गई कीमत, ऐसी confirmation जो सिर्फ़ कोई इंसान दे सकता है, कोई भी ऐसी चीज़ जिसे model गढ़कर गलत कर सकता है।

**Dependencies** वे parameters हैं जिन्हें आपके अपने functions भरते हैं। आप parameter को annotate करते हैं, function का नाम देते हैं, और tool चलने से पहले SDK उसे call करता है।

## एक declare करें {#declare-one}

parameter के type को `Annotated[...]` में लपेटें और `Resolve(fn)` जोड़ें:

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` **resolver** है: सादा function, जिसे SDK `reserve_book` से पहले चलाता है और जिसकी return value `stock` argument बन जाती है।
* इसका `title` parameter tool का अपना `title` argument ही है, जिसका मिलान **नाम से** होता है। resolver को ठीक वही validated value दिखती है जो tool body को दिखेगी।
* tool body ऐसे `Stock` से शुरू होती है जो पहले से मौजूद है। tool में कोई lookup code नहीं, कोई "अगर यह न मिले तो" वाली भूमिका नहीं।

!!! info
    अगर आपने FastAPI इस्तेमाल किया है, तो यह `Depends` है। वही तरीका, वही वजह: function बताता है
    कि उसे क्या चाहिए, framework वह देता है, और सारी wiring type annotation में रहती है।

### model को नहीं दिखता {#invisible-to-the-model}

यह रहा वह input schema जो `tools/list` `reserve_book` के लिए बताता है:

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

एक ही property। **[Context](context.md)** के `Context` की तरह, resolve किया गया parameter आपके और SDK के बीच का अनुबंध है: `stock` schema में नहीं है, model को इसके बारे में कभी नहीं बताया जाता, और जो client फिर भी `stock` value भेजता है उसे अनदेखा कर दिया जाता है। resolver की value ही वह अकेली value है जो आपके tool को मिल सकती है।

आखिरी बात ही असली बात है। जो parameter model दे ही नहीं सकता, उसे model गलत भी नहीं कर सकता।

### इसे आज़माएँ {#try-it}

server को MCP Inspector के साथ चलाएँ:

```console
uv run mcp dev server.py
```

`reserve_book` के form में सिर्फ़ एक `title` field है। `stock` उस पर कहीं नहीं है। इसे `Dune` के साथ call करें:

```text
Reserved 'Dune' (6 copies left).
```

tool body ने खुद कुछ भी नहीं खोजा: पहले `check_stock` चला, और उसका लौटाया `Stock` argument बनकर आया। `Neuromancer` आज़माएँ और वही resolver tool को शून्य थमा देता है।

!!! tip
    आप tool body में सीधे `check_stock(title)` call भी कर सकते हैं। इसे dependency तब declare करें
    जब value एक helper call से ज़्यादा की हकदार हो: stock की ज़रूरत वाला हर tool वही parameter
    declare करता है, और चाहे कितने भी tools इसे declare करें, SDK resolver को प्रति call ज़्यादा से
    ज़्यादा एक बार चलाता है। अगले sections बाकी जोड़ते हैं: एक-दूसरे पर निर्भर resolvers, और user से
    पूछने वाले resolvers।

## Dependencies की dependencies {#dependencies-of-dependencies}

resolver उसी annotation से अपनी खुद की dependencies declare कर सकता है:

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` `check_stock` पर निर्भर है। SDK graph को क्रम से चलाता है: पहले stock, फिर estimate, फिर tool।
* `stock` और `delivery` दोनों को आखिरकार `check_stock` चाहिए, लेकिन यह **प्रति call एक बार** चलता है। एक inventory lookup, दो consumers।
* register करने को कुछ नहीं है। annotations ही graph **हैं**।

!!! check
    "प्रति call एक बार" पर आँख मूँदकर भरोसा न करें। `check_stock` में एक `print` डालें और Inspector से
    `order_book` call करें: प्रति call एक line। दो consumers, एक lookup।

SDK graph का विश्लेषण तब करता है जब tool register होता है, न कि जब उसे call किया जाता है। ऐसा parameter जिसे वह वर्गीकृत न कर सके - न `Context`, न `Resolve(...)`, न किसी tool argument का नाम - और resolvers का कोई cycle, दोनों startup पर `InvalidSignature` raise करते हैं। server किसी भी client के जुड़ने से पहले ही fail हो जाता है, और error में गड़बड़ी वाले parameter या resolver का नाम होता है।

resolver के parameters ठीक tool के parameters की तरह resolve होते हैं: कोई और `Resolve(...)`, नाम से tool के अपने arguments, या `Context` - `ctx.headers`, lifespan object, सब कुछ।

!!! warning
    HTTP transports पर `Context` में `ctx.headers` शामिल होते हैं। headers **client का भेजा हुआ input** हैं,
    किसी भी tool argument की तरह: locale या feature flag के लिए ठीक, पहचान के लिए कभी नहीं। caller कौन
    है, यह आपकी authorization layer (**[Authorization](../run/authorization.md)**) से आता है, किसी ऐसे header से नहीं जिसे कोई भी set कर सकता है।

!!! tip
    **प्रति call एक बार** का मतलब ठीक यही है: अगला `tools/call` `check_stock` को फिर से चलाता है। ऐसा resource
    जिसे एक request से ज़्यादा जीना चाहिए - database pool, HTTP client - उसकी जगह **[Lifespan](lifespan.md)** में है, और
    resolver उस तक `ctx.request_context.lifespan_context` के ज़रिए पहुँच सकता है।

## तभी पूछें जब ज़रूरी हो {#ask-when-you-must}

resolver को जवाब पता हो, यह ज़रूरी नहीं। वह `Elicit(message, Model)` लौटा सकता है और SDK user से पूछ लेता है - यानी **[Elicitation](elicitation.md)** की machinery, जो आपके लिए चलाई जाती है:

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* stock में हो: `confirm_backorder` सीधे `Backorder` लौटाता है। **कोई सवाल नहीं, कोई round-trip नहीं।** user को तभी टोका जाता है जब उसका जवाब मायने रखता हो।
* stock में न हो: SDK elicitation भेजता है, जवाब को `Backorder` के हिसाब से validate करता है, और उसे inject कर देता है। आपका resolver protocol को कभी छूता तक नहीं।
* tool `backorder.confirm` को किसी भी दूसरे argument की तरह पढ़ता है। **नहीं** कहना भी एक जवाब है: elicitation `confirm=False` के साथ accept होता है, tool चलता है, और कोई order नहीं दिया जाता। पूछना tool body की plumbing नहीं, एक precondition बन गया।

और अगर user जवाब ही न दे - सवाल decline कर दे, या cancel कर दे?

!!! check
    `Neuromancer` के लिए `order_book` चलाएँ और सवाल decline करें। annotation
    `Annotated[Backorder, Resolve(...)]` के रूप में लिखी हो तो tool body कभी नहीं चलती; call ऐसे error
    result के साथ fail होता है जिसे model पढ़ सकता है:

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

precondition के लिए यही सही default है: जवाब नहीं, तो order नहीं। जब decline होना ऐसा नतीजा हो जिसे आपका tool खुद संभालना चाहे - backorder छोड़ दे पर फिर भी कोई दूसरा title सुझाए - तो इसके बजाय `ElicitationResult[Backorder]` annotate करें और tool को पूरा accept/decline/cancel नतीजा मिलता है जिस पर वह branch कर सके। **[Elicitation](elicitation.md)** वह रूप दिखाता है, और पूछने के बारे में बाकी सब भी: schema के नियम, तीनों जवाब, बातचीत का client वाला पक्ष।

!!! info
    framework सवाल का transport negotiate हुए protocol version से चुनता है; ऊपर का code दोनों पर एक जैसा
    है। **2026-07-28** और उसके बाद सवाल एक multi-round-trip `tools/call` के भीतर जाता है - server उसे
    लौटाता है, client का `elicitation_callback` उसका जवाब देता है, और `Client` आपके लिए call को फिर से
    आज़माता है (**[Multi-round-trip requests](multi-round-trip.md)**)। **2025-11-25** और उससे पहले यह call के
    बीच में एक synchronous elicitation request होती है। हर सवाल प्रति call ठीक एक बार पूछा जाता है - यह
    गारंटी सवाल के बारे में है, resolver के बारे में नहीं। multi-round-trip रूप में, जब भी call किसी सवाल के
    बाद फिर से शुरू होता है, कोई भी resolver दोबारा चल सकता है, इसलिए `return Elicit(...)` से पहले का code
    उन हर rounds पर चलता है; फिर दर्ज किया गया जवाब दोहराए गए सवाल को user से दोबारा पूछे बिना पूरा कर
    देता है। दर्ज जवाब सिर्फ़ तभी देखा जाता है जब resolver पूछता है; जो resolver पूछे **बिना** जवाब दे देता
    है, जैसे `check_stock`, वह हमेशा अपनी खुद की गणना की गई value देता है। चूँकि हर जवाब वापस उसके सवाल
    से मिलाया जाता है, elicit करने वाले resolver को अपना सवाल tool के arguments और पहले के जवाबों से
    deterministic ढंग से बनाना होगा। प्रति call बनने वाली value (`default_factory` id, timestamp) हर round
    पर फिर से बनती है और ऐसे सवाल में नहीं आनी चाहिए जिससे जवाब को बँधना है। ऐसे अस्थिर data से बना सवाल
    हर दर्ज जवाब को बासी दिखा देता है, इसलिए server उसे हर round पर फिर से पूछता है, जब तक client की
    round limit call को खत्म नहीं कर देती।

## user से नहीं, client से पूछें {#ask-the-client-not-the-user}

Elicitation उन तीन सवालों में से एक है जो resolver पूछ सकता है, और multi-round-trip flow इनके अलावा कोई और सवाल नहीं होने देता। बाकी दो user के बजाय **client** के पास जाते हैं: client के ज़रिए LLM call चलाने के लिए `Sample(...)` लौटाएँ (एक `sampling/createMessage` request), या client के मौजूदा roots लाने के लिए `ListRoots()`। दोनों में से किसी का accept/decline नतीजा नहीं होता; consumer सीधे result type annotate करता है, `CreateMessageResult` (जब request में `tools` या `tool_choice` हो तो `CreateMessageResultWithTools`) या `ListRootsResult`:

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* framework इन्हें ठीक `Elicit` की तरह route करता है: **2026-07-28** पर multi-round-trip `tools/call` के भीतर, **2025-11-25** पर standalone server->client request के ज़रिए। declare न की गई capability call को `-32021` protocol error के साथ मना कर देती है (`sampling`, `roots`, form-mode `elicitation`; जब request में `tools` या `tool_choice` हो तो `sampling.tools`)।
* ऊपर वाला info box सवालों के बारे में जो कुछ कहता है, वह बिना बदलाव लागू होता है: `Sample` request का मिलान उसके दर्ज result से उसके हूबहू rendering से होता है, इसलिए उसे tool के arguments और पहले के जवाबों से deterministic ढंग से बनाएँ; तब client LLM call की कीमत प्रति tool call एक बार चुकाता है, प्रति round एक बार नहीं। दर्ज result बाकी call भर `request_state` में साथ चलता है, इसलिए बहुत बड़ा completion बचे हुए हर round-trip को भारी बना देता है।
* standalone sampling और roots **features** 2026-07-28 पर deprecated हैं (SEP-2577)। जिन नए servers को client के model की ज़रूरत है वे इसी carrier के ज़रिए पूछते हैं; जिन्हें नहीं है उन्हें सीधे किसी LLM provider से integrate करना चाहिए। `"none"` के अलावा `include_context` की values खुद deprecated हैं; उनसे बचें।

## सारांश {#recap}

* tool parameter पर `Annotated[T, Resolve(fn)]`: SDK `fn` चलाता है और उसकी return value inject करता है।
* resolve किया गया parameter model को नहीं दिखता और कोई client उसे भेज नहीं सकता। जो values model को गढ़नी नहीं चाहिए - कीमतें, पहचान, अनुमतियाँ - उनकी जगह यहीं है।
* resolver के parameters उसी तरह resolve होते हैं: `Context`, कोई और `Resolve(...)`, या नाम से कोई tool argument। graph हर resolver को प्रति round ज़्यादा से ज़्यादा एक बार चलाता है, चाहे उसके कितने भी consumers हों; हर सवाल ठीक एक बार पूछा जाता है, और call के किसी सवाल के बाद फिर से शुरू होने पर कोई भी resolver दोबारा चल सकता है।
* खराब graphs registration के समय `InvalidSignature` के साथ fail होते हैं, call के बीच में नहीं।
* user से पूछने के लिए `Elicit(message, Model)` लौटाएँ, सिर्फ़ तब जब ज़रूरी हो। बिना wrap की annotations decline पर abort करती हैं; `ElicitationResult[T]` tool को branch करने देती है।
* client से LLM completion या roots की सूची माँगने के लिए `Sample(...)` या `ListRoots()` लौटाएँ; सादा result inject हो जाता है।

server startup पर एक बार जो state बनाता है, और handler उस तक कैसे पहुँचता है, वह **[Lifespan](lifespan.md)** page है।
