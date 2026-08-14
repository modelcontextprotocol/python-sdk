---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# Lifespan {#lifespan}

ज़्यादातर असली servers पूरी ज़िंदगी भर कुछ न कुछ संभाले रखते हैं: database pool, HTTP client, load किया हुआ model।

इसे हर call पर दोबारा बनाना कोई नहीं चाहता, और इसे साफ़-सुथरे ढंग से बंद करना ज़रूर चाहिए। **lifespan** इसी के लिए है।

## Typed lifespan {#a-typed-lifespan}

lifespan एक `@asynccontextmanager` है जिसे server मिलता है और जो **एक object** `yield` करता है। आप जो भी yield करते हैं, वह server के चलते रहने तक हर handler को उपलब्ध रहता है।

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

इसे नीचे से ऊपर पढ़ें:

* `app_lifespan` `yield` से **पहले** `Database` को connect करता है और उसके **बाद**, `finally` में, disconnect करता है। यही startup और shutdown है।
* यह `AppContext` yield करता है, एक सादा dataclass जिसमें वे चीज़ें हैं जो आपने set up कीं। आज एक field, कल दस।
* `MCPServer("Bookshop", lifespan=app_lifespan)` ही पूरी wiring है।
* tool के अंदर, yield किया गया object `ctx.request_context.lifespan_context` है।

lifespan **एक बार** चलता है। server शुरू होने पर (पहली request से पहले) इसमें प्रवेश होता है और server रुकने पर इससे बाहर निकला जाता है। बीच की हर request वही `AppContext` साझा करती है।

!!! info
    अगर आपने FastAPI का `lifespan` लिखा है, तो आप यह पहले से जानते हैं। वही decorator, वही `yield`, वही `finally`।

### model को क्या दिखता है {#what-the-model-sees}

कुछ नया नहीं। `ctx` एक **Context** parameter है, इसलिए SDK इसे inject करता है और यह input schema तक कभी नहीं पहुँचता:

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` ही एकमात्र argument है जो model दे सकता है। lifespan आपके server का अपना मामला है।

`@mcp.resource()` और `@mcp.prompt()` functions भी `ctx` parameter ले सकते हैं, जिसे सिर्फ़ `Context` लिखा जाता है; इसकी वजह अगला section बताता है। `ctx` में जो कुछ भी है, वह सब **[Context](context.md)** में है।

### यह सच में typed है {#it-really-is-typed}

annotation को फिर से देखें: `ctx: Context[AppContext]`।

इसी एक type parameter की वजह से आपके type checker के लिए `ctx.request_context.lifespan_context` एक `AppContext` **है**। `.db` autocomplete होता है; `.dbb` server चलाने से पहले ही error है।

इसकी जगह सिर्फ़ `Context` लिखें तो `lifespan_context` का type `dict[str, Any]` हो जाता है: type checker के पास यह जानने का कोई तरीका नहीं कि आपके lifespan ने क्या yield किया। runtime पर object फिर भी मौजूद रहता है; बस मदद चली जाती है।

!!! warning
    `Context[AppContext]` **सिर्फ़ tools के लिए** लिखने का तरीका है। इसे किसी `@mcp.resource()` या
    `@mcp.prompt()` function पर लगाएँ तो उस handler की हर call विफल हो जाती है। client को error वापस मिलता है,
    और server log बताता है क्यों:

    ```text
    Context is not available outside of a request
    ```

    resources और prompts में सिर्फ़ `ctx: Context` लिखें। आपके lifespan ने जो object yield किया वह
    runtime पर अब भी `ctx.request_context.lifespan_context` ही है; आप type parameter छोड़ते हैं,
    object नहीं।

!!! tip
    lifespan हमेशा होता है। अगर आप कोई pass नहीं करते, तो SDK का default एक खाली `dict` yield करता है,
    इसलिए `ctx.request_context.lifespan_context` `{}` होता है, कभी `None` नहीं। इसी default की वजह से
    सिर्फ़ `Context` लिखने पर इसका type `dict[str, Any]` होता है।

## इसे होते हुए देखें {#watch-it-happen}

"startup पहली request से पहले चलता है" ऐसा वाक्य है जिस पर आपको बिना देखे भरोसा नहीं करना पड़ना चाहिए।

server को सिर्फ़ lifecycle तक सीमित कर दें: `Database` को एक `connected` flag दें, `connect()` और `disconnect()` में उसे पलटें, और एक tool जोड़ें जो उसकी स्थिति बताए।

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` module level पर एक ही वजह से है: ताकि आप इसे server के **बाहर** से देख सकें।

!!! check
    तीन पल, तीन values:

    * server शुरू होने से पहले, `database.connected` `False` है। module import करने से कुछ connect नहीं हुआ।
    * जब यह चल रहा हो, `database_status` call करें और result `"connected"` मिलता है।
    * server रोकें और `finally` block चलता है: `database.connected` फिर से `False` है।

    काम ठीक वहीं हुआ जहाँ आपने उसे रखा: `yield` के आसपास, न import के समय और न हर request पर।

## सारांश {#recap}

* `lifespan=` एक `@asynccontextmanager` लेता है जिसे server मिलता है और जो एक object `yield` करता है।
* `yield` से पहले का code startup है। उसके बाद का `finally` shutdown है।
* यह एक बार चलता है, server की पूरी ज़िंदगी के इर्द-गिर्द, हर request पर नहीं।
* आप जो भी `yield` करते हैं, वह हर tool, resource और prompt में `ctx.request_context.lifespan_context` है।
* `ctx: Context[AppContext]` tools में इस access को पूरी तरह typed बना देता है। resources और prompts सिर्फ़ `Context` लेते हैं।
* `lifespan=` न हो तो खाली `dict` मिलता है, कभी `None` नहीं।

जो handler call के बीच रुककर user से वह पूछता है जो सिर्फ़ user ही जानता है, वह **[Elicitation](elicitation.md)** है।
