---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Context {#the-context}

tool के arguments model से आते हैं। बाकी सब कुछ (जिस request को आप serve कर रहे हैं, जिस server में आप हैं, client से वापस बात करने का तरीका) एक ही object से आता है: **`Context`**।

न आपको इसे बनाना है, न configure करना है। बस माँगना है।

## इसे माँगें {#ask-for-it}

किसी भी tool में `Context` से annotate किया गया parameter जोड़ें:

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* SDK हर request के लिए नया `Context` बनाता है और उसे pass करता है।
* parameter का **नाम मायने नहीं रखता**। `ctx`, `context`, `c`: SDK इसे annotation से पहचानता है।
* resources और prompts भी इसी तरह एक declare कर सकते हैं।
* `ctx.request_id` उस request की id है जिसे आपका function अभी serve कर रहा है।

!!! info
    अगर आपने FastAPI इस्तेमाल किया है, तो यह तरीका आपने देखा है: framework के अपने type
    (वहाँ `Request`, यहाँ `Context`) वाला parameter declare करें और framework उसे दे देता है। कुछ register नहीं करना, कुछ
    configure नहीं करना: type annotation ही पूरा mechanism है।

### model को नहीं दिखता {#invisible-to-the-model}

यही बात अच्छे से समझ लेने की है। यह रहा वह input schema जो `tools/list` `search_books` के लिए बताता है:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

एक ही property। `ctx` कोई argument नहीं है: यह schema में कभी नहीं आता, model को इसके बारे में कभी नहीं बताया जाता, और कोई client इसे भर नहीं सकता। यह आपके और SDK के बीच का समझौता है, wire पर नहीं दिखता।

### इसे आज़माएँ {#try-it}

MCP Inspector के साथ server चलाएँ:

```console
uv run mcp dev server.py
```

`search_books` के form में सिर्फ़ एक `query` field है। इसे `dune` के साथ call करें:

```text
[request 3] Found 3 books matching 'dune'.
```

संख्या वही है जो यह request संयोग से थी। tool को दोबारा call करें और यह बदल जाती है: हर request को अपना `Context` मिलता है।

## यह आपको क्या देता है {#what-it-gives-you}

inject किया गया object छोटा है। `request_id` के अलावा:

* `await ctx.read_resource(uri)`: tool के अंदर से server का **अपना** resource पढ़ें। अगला section।
* `await ctx.report_progress(progress, total, message)`: लंबे call के दौरान caller को progress भेजते रहें। पूरी जानकारी **[Progress](progress.md)** में है।
* `await ctx.elicit(message, schema)` और `await ctx.elicit_url(...)`: tool को रोककर user से सवाल पूछें। यह **[Elicitation](elicitation.md)** है।
* `ctx.session`: इस client के साथ बातचीत का server वाला पक्ष। client को भेजे जाने वाले notifications यहीं रहते हैं; आखिरी section इसका इस्तेमाल करता है।
* `ctx.headers`: transport जो request headers लाया, या stdio पर `None`। custom header `(ctx.headers or {}).get("x-...")` से पढ़ें। headers client का दिया हुआ input हैं - locale या feature flag के लिए ठीक, identity के लिए कभी नहीं।
* `ctx.request_context`: हर request का raw record। जिस field की ज़रूरत पड़ेगी वह है `lifespan_context`, वह object जो आपके startup code ने yield किया था (**[Lifespan](lifespan.md)** देखें)।

logging जानबूझकर इस सूची में नहीं है। server Python के `logging` module से log करता है, किसी भी दूसरे Python program की तरह। **[Logging](logging.md)** वह छोटा page है जो बताता है क्यों।

!!! tip
    injection सिर्फ़ उसी function के लिए होता है जिसे आपने register किया। आपका tool जिस helper को call करता है, उसे
    अपना `Context` नहीं मिलता; `ctx` को साधारण argument की तरह नीचे pass करें। कहीं और से लाने के लिए कोई ambient
    "current context" नहीं है।

## अपने resources पढ़ें {#read-your-own-resources}

server के resources सिर्फ़ clients के लिए नहीं हैं। tool भी उन्हें पढ़ सकता है:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` URI को उसी registry से resolve करता है जो `resources/read` को serve करती है, इसलिए tool को वही मिलता है जो client को मिलता: `ReadResourceContents` का iterable, हर content block के लिए एक। इस URI के लिए एक है:

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` ठीक वही है जो `genres()` ने लौटाया। सच का एक ही स्रोत: client resource को browse करता है, आपके tools उसे इस्तेमाल करते हैं, कोई string की copy नहीं बनाता।
* `describe_catalog` का इकलौता parameter `Context` है, इसलिए इसके input schema में **कोई property ही नहीं** है। model इसे `{}` के साथ call करता है।

## client को बताएँ कि सूची बदल गई {#tell-the-client-the-list-changed}

server जो देता है वह import time पर तय नहीं है। runtime पर tool register करें, फिर client को बताएँ:

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` एक साधारण function को tool की तरह register करता है: name, description और schema ठीक वैसे ही निकाले जाते हैं जैसे `@mcp.tool()` निकालता।
* `await ctx.session.send_tool_list_changed()` `notifications/tools/list_changed` भेजता है। जिस client को यह मिलता है वह `tools/list` दोबारा call करता है और `recommend_book` देखता है।

इसके साथी हैं `send_resource_list_changed()`, `send_prompt_list_changed()`, और किसी एक खास resource में बदलाव के लिए `send_resource_updated(uri)`।

2026-07-28 connection पर clients को change notifications सिर्फ़ उस `subscriptions/listen` stream पर मिलते हैं जो उन्होंने खोला, इसलिए ऊपर के `send_*` methods उन streams तक नहीं पहुँचते। `Context` के publish methods हर subscribed stream पर एक साथ deliver करते हैं: `await ctx.notify_tools_changed()`, `await ctx.notify_prompts_changed()`, `await ctx.notify_resources_changed()`, और `await ctx.notify_resource_updated(uri)`। पूरी जानकारी, replicas पर scale out करने समेत, **[Subscriptions](subscriptions.md)** में है।

!!! check
    जब तक कोई `enable_recommendations` नहीं चलाता, जिस tool का आप वादा कर रहे हैं वह मौजूद नहीं है। फिर भी उसे call
    करें और नतीजा एक error है जिसे model पढ़ सकता है:

    ```text
    Unknown tool: recommend_book
    ```

    `enable_recommendations` चलाएँ, और ठीक वही call सफल हो जाता है। tool की सूची सच में
    dynamic है: `tools/list` वही दिखाता है जो **अभी** register है।

## सारांश {#recap}

* किसी parameter को `Context` से annotate करें (tool, resource या prompt में) और SDK उसे inject कर देता है। नाम आपकी मर्ज़ी का।
* यह model को नहीं दिखता: input schema में हमेशा सिर्फ़ आपके असली arguments होते हैं।
* `ctx.request_id` request की पहचान है; `ctx.request_context.lifespan_context` वह है जो आपके startup ने yield किया।
* `await ctx.read_resource(uri)` से tool server के अपने resources पढ़ सकता है।
* `ctx.session` client तक वापस जाने का channel है: `send_tool_list_changed()` और उसके साथी उसे बताते हैं कि बदली गई सूची दोबारा fetch करे।
* progress reporting और elicitation भी `Context` से शुरू होते हैं; दोनों का अपना page है।

जो parameters model कभी नहीं देखता, और जिन्हें आपके अपने functions भरते हैं, वे **[Dependencies](dependencies.md)** हैं।
