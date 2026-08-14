---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# Elicitation {#elicitation}

जो tool अपना काम आधा कर चुका हो और उसके पास बस एक जवाब की कमी हो, उसका fail होना ज़रूरी नहीं।

**Elicitation** उसे पूछने देता है। tool call के बीच में user को एक सवाल मिलता है, और उसका जवाब उसी function call में वापस आ जाता है।

इसके दो mode हैं:

* **Form mode**: आपको एक value चाहिए (confirmation, तारीख, मात्रा)। आप fields बताते हैं, client form render करता है।
* **URL mode**: आपको user को कहीं और भेजना है (OAuth consent screen, payment page)। user वहाँ जो कुछ भी करता है, वह protocol से होकर नहीं गुज़रता।

और पूछने के दो तरीके हैं। जिसे पहले अपनाना चाहिए वह है **resolver**: आप सवाल को एक parameter पर टाँग देते हैं, और SDK पूछ लेता है - किसी भी connection पर, client चाहे किसी भी protocol पीढ़ी का हो। सीधा तरीका, `await ctx.elicit(...)`, *server* से *client* को जाने वाली request है, एक ऐसा channel जो सिर्फ़ legacy connection (spec version 2025-11-25 या उससे पहले) वाले client के लिए ही मौजूद होता है। दोनों इस page पर हैं; resolver से शुरू करें।

## resolver से पूछना {#ask-with-a-resolver}

जो सवाल पूरे tool को रोके रखता है - **पक्का? तीन मिलते-जुलते accounts में से कौन-सा?** - उसे tool body से निकालकर **resolver** में रखा जा सकता है, और framework उसे आपके लिए पूछ लेता है।

`Annotated[T, Resolve(fn)]` से annotate किया गया parameter tool body से पहले `fn` चलाकर भरा जाता है। जब resolver को value पहले से पता हो तो वह उसे सीधे लौटाता है, वरना `Elicit(...)` लौटाता है ताकि framework पूछ ले:

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` tool के अपने `path` argument को नाम से पढ़ता है, folder की सूची बनाता है, और **सिर्फ़ तभी elicit करता है जब ज़रूरी हो** - खाली folder client तक एक भी round trip के बिना `Confirm(ok=True)` में resolve हो जाता है।
* `delete_folder` `ElicitationResult[Confirm]` annotate करता है, इसलिए framework पूरा नतीजा inject करता है और tool हर स्थिति को `match` करता है: accept-and-confirm, accept-but-keep (`ok=False`), decline, cancel।
* `confirm` parameter tool के input schema में कभी नहीं दिखता - client `path` देता है, resolver `confirm` देता है।

जब tool को branch करने की ज़रूरत न हो तो इसके बजाय unwrapped model (`Annotated[Confirm, Resolve(confirm_delete)]`) annotate करें: accept पर उसे model मिलता है और decline या cancel पर call एक error के साथ abort हो जाता है।

resolver **हर** connection पर काम करता है। legacy connection वाले client को SDK सवाल सीधे भेजता है; **2026-07-28** connection पर SDK call से सवाल **लौटाता** है, और client की अगली कोशिश जवाब साथ लाती है। आपके resolver को फ़र्क कभी पता नहीं चलता; नीचे जो होता है, वह **[Multi-round-trip requests](multi-round-trip.md)** है।

पूछना तो resolver के कामों में से सिर्फ़ एक है। सामान्य तंत्र - बिना पूछे compute होने वाली dependencies, dependencies की dependencies, model क्या दे सकता है और क्या नहीं - **[Dependencies](dependencies.md)** page पर है।

## tool के अंदर से पूछना {#ask-from-inside-the-tool}

tool अपनी body के बीच में रुककर भी पूछ सकता है।

!!! warning
    `ctx.elicit()` और `ctx.elicit_url()` *server* से *client* को जाने वाली requests हैं - एक
    ऐसा channel जो सिर्फ़ legacy connection (spec version **2025-11-25** या उससे पहले) वाले
    client के लिए मौजूद होता है। **2026-07-28** connection पर server की ओर से शुरू की गई कोई
    request नहीं होती, इसलिए ये calls fail हो जाते हैं। resolver दोनों पर काम करता है।
    पूरी जानकारी **[Protocol versions](../protocol-versions.md)** में है।

`await ctx.elicit()` एक message और एक Pydantic model लेता है:

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** parameter ही आपको `ctx.elicit` देता है; कोई भी tool इसे ले सकता है। उस object का अपना page है: **[Context](context.md)**।
* `AlternativeDate` उस जवाब का **schema** है जो आप चाहते हैं।
* tool `async def` है। होना ही चाहिए: यह बीच में रुककर किसी इंसान का इंतज़ार करता है।
* किसी भी दूसरी तारीख पर tool तुरंत लौट आता है। यह सिर्फ़ तभी पूछता है जब ज़रूरी हो।
* user जो तारीख accept करता है, वह `book_table` से ही होकर वापस जाती है। जवाब भी बाकी input की तरह input ही है: अगर विकल्प वाली तारीख भी पूरी तरह booked है तो उसके बारे में फिर से पूछा जाता है, आँख मूँदकर confirm नहीं किया जाता।

### client को क्या मिलता है {#what-the-client-receives}

client को आपका message मिलता है और उसके साथ model से generate किया गया एक JSON Schema:

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

वही schema form है। `Field(description=...)` label है; default input को पहले से भर देता है और field को optional बना देता है। यह वही Pydantic-to-JSON-Schema तंत्र है जो **[Tools](../servers/tools.md)** tool के arguments के लिए बताता है।

!!! warning
    elicitation schema tool के input schema जितना expressive नहीं होता। सिर्फ़ flat, primitive
    fields: `str`, `int`, `float`, `bool`, या strings का `Literal` (यह `enum` बन जाता है)।
    model के अंदर model रखें और `ctx.elicit` client को कुछ भी भेजे जाने से पहले ही raise कर देता है:

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    आप किसी इंसान को काम के बीच में टोक रहे हैं। अगर जवाब में nesting चाहिए, तो उसे tool का
    argument होना चाहिए था।

### तीन जवाब {#the-three-answers}

`result.action` बताता है कि user ने क्या किया, और संभावनाएँ ठीक तीन हैं:

* `"accept"`: user ने form submit किया। `result.data` एक `AlternativeDate` instance है, पहले से validated।
* `"decline"`: user ने मना कर दिया।
* `"cancel"`: user ने बिना कुछ चुने सवाल को हटा दिया।

`result.data` सिर्फ़ `"accept"` पर ही मौजूद होता है, इसीलिए उदाहरण पहले `result.action` जाँचता है। आपका type checker यह क्रम लागू करता है: `result.action == "accept"` के बाद `result.data` एक `AlternativeDate` है; उससे पहले `.data` है ही नहीं।

इनकार कोई error नहीं है। decline का क्या मतलब है, यह tool तय करता है (यहाँ, कोई booking नहीं) और model को सामान्य रूप से जवाब देता है।

!!! tip
    जवाब आपके code तक पहुँचने से पहले आपके model के विरुद्ध validate होता है। जो client
    `bool` के लिए `"maybe"` भेजता है, वह आपकी booking को खराब नहीं करता: call
    schema-mismatch error के साथ fail हो जाता है, आपका `if` कभी नहीं चलता।

## user को URL पर भेजना {#send-the-user-to-a-url}

कुछ चीज़ें model या client से होकर कभी नहीं गुज़रनी चाहिए: credentials, card numbers, OAuth consent। इनके लिए आप data नहीं माँगते; आप user से कहीं जाने को कहते हैं:

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` message, जाने के लिए **URL**, और आपकी चुनी हुई एक `elicitation_id` लेता है: कोई भी string जो आपके server के भीतर इस elicitation को पहचानती हो।
* result में एक action है और कुछ नहीं। `"accept"` का मतलब है user URL खोलने के लिए राज़ी हुआ, यह **नहीं** कि उसने दूसरी तरफ़ का काम पूरा कर लिया।
* payment out of band होता है, user के browser और आपके payment provider के बीच। MCP से होकर कोई content कभी वापस नहीं आता।

दूसरा tool देखें। जब आपके server को पता चलता है कि out-of-band flow पूरा हो गया (webhook, poll; यहाँ इसे दूसरे tool के रूप में दिखाया गया है), तो `ctx.session.send_elicit_complete(...)` उसी `elicitation_id` के साथ `notifications/elicitation/complete` भेजता है। इसी से client को पता चलता है कि वह *"waiting for payment..."* दिखाना बंद कर सकता है। इसके बिना client सिर्फ़ अंदाज़ा लगा सकता है।

## client की तरफ़ {#the-client-side}

servers पूछते हैं। clients `Client(...)` को एक **`elicitation_callback`** देकर जवाब देते हैं:

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* एक ही callback दोनों modes संभालता है। `params` `ElicitRequestFormParams` और `ElicitRequestURLParams` का union है; `isinstance` ही branch है।
* URL के लिए, आप user को `params.url` दिखाते हैं और उसका चुना हुआ action लौटाते हैं। कभी कोई `content` नहीं।
* form के लिए, असली application `params.requested_schema` render करता है और user का input `content` के रूप में लौटाता है। यह वाला हमेशा एक तयशुदा जवाब के साथ हाँ कहता है, जो test में ठीक वैसा ही callback है जैसा आप चाहते हैं।
* callback देना ही **capability declaration** भी है: इसी से server को पता चलता है कि इस client से पूछा जा सकता है। client server के लिए और किन चीज़ों का जवाब दे सकता है, वह **[Client callbacks](../client/callbacks.md)** में है।

!!! info
    elicitation *server* से *client* को जाने वाली request है, और ऐसी requests सिर्फ़
    classic-handshake session पर ही होती हैं, इसीलिए यह client `mode="legacy"` देता है।
    **2026-07-28** connection पर tool इसके बजाय call से सवाल **लौटाकर** पूछता है;
    वह flow **[Multi-round-trip requests](multi-round-trip.md)** है।

### इसे आज़माएँ {#try-it}

`ctx.elicit` वाले form-mode `server.py` (`book_table` वाला) को Streamable HTTP पर शुरू करें (one-liner **[अपना server चलाना](../run/index.md)** में है), फिर client का `main()` चलाएँ और `book_table` से Christmas के दिन के लिए पूछें।

callback उसे भेजा गया सवाल print करता है:

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

यह `{"accept_alternative": True, "date": "2025-12-27"}` से जवाब देता है, और tool, जो इस पूरे समय `await ctx.elicit(...)` के अंदर इंतज़ार कर रहा था, booking पूरी कर देता है:

```text
Booked a table for 2 on 2025-12-27.
```

अब URL-mode वाला `server.py` लगाएँ और उसी `main()` को `pay_deposit` की ओर कर दें: वही callback दूसरी branch लेता है, payment link print करता है, और tool *"Complete the payment in your browser."* के साथ लौटता है। एक round trip, call के बीच में, दोनों दिशाओं में।

!!! check
    अब `Client` से `elicitation_callback=` हटाएँ और `book_table` को Christmas के दिन के लिए
    फिर से call करें। पूरा call एक protocol error के साथ fail हो जाता है:

    ```text
    Elicitation not supported
    ```

    जिस client ने कोई callback register नहीं किया, उसने `elicitation` capability कभी declare ही
    नहीं की, इसलिए पूछने के लिए कोई है ही नहीं। आपके tool को `"decline"` नहीं मिला; उसे exception
    मिला। इसे ध्यान में रखकर design करें: हर elicitation के पास "अगर मैं पूछ न सकूँ तो?" का
    एक समझदार जवाब होना चाहिए।

## सारांश {#recap}

* `Annotated[T, Resolve(fn)]` से annotate किया गया parameter resolver भरता है, जो पूछना ज़रूरी होने पर `Elicit(...)` लौटाता है। यह हर connection पर काम करता है।
* schema एक flat Pydantic model है: सिर्फ़ primitive fields, वापसी पर validate होते हैं।
* `result.action` `"accept"`, `"decline"` या `"cancel"` होता है; `result.data` सिर्फ़ accept पर मौजूद होता है।
* `await ctx.elicit(message, schema=Model)` tool body के अंदर से पूछता है, और `await ctx.elicit_url(message, url, elicitation_id)` उन सब चीज़ों के लिए है जो model से होकर नहीं गुज़रनी चाहिए (`ctx.session.send_elicit_complete(elicitation_id)` बताता है कि out-of-band हिस्सा पूरा हो गया)। दोनों server-to-client requests हैं: इन्हें legacy connection वाला client चाहिए।
* client एक `elicitation_callback` से जवाब देता है, params के type पर branch करके; उसे register करना ही capability declare करना है।
* 2026-07-28 connection पर server सवाल को push करने के बजाय लौटाता है; वही callback **[Multi-round-trip requests](multi-round-trip.md)** से भरता है।

उस return के नीचे जो कुछ भी है (retry loop, `requestState` की सुरक्षा, इसे खुद चलाना), वह **[Multi-round-trip requests](multi-round-trip.md)** है।
