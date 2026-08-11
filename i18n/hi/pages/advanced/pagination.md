---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# Pagination {#pagination}

ज़्यादातर servers को इसकी ज़रूरत कभी नहीं पड़ती।

`MCPServer` हर `list_*` request का जवाब अपने पास मौजूद सब कुछ देकर करता है, एक ही page में, `next_cursor=None` के साथ। कुछ दर्जन tools, resources या prompts के लिए यही सही जवाब है और configure करने को कुछ नहीं है।

Pagination उस server के लिए है जिसकी resource list असल में एक database है: हज़ारों rows जिन्हें वह एक ही response में serialize करने से मना करता है। Protocol का जवाब है **cursor**: server एक page के साथ एक opaque token लौटाता है, और client अगला page पाने के लिए वही token वापस भेजता है।

`@mcp.resource()` में इसके लिए कोई hook नहीं है। Paging करने के लिए आप list handler ख़ुद लिखते हैं, **[low-level Server](low-level-server.md)** पर।

## Paging करने वाला server {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* Low-level `Server` पर handlers constructor arguments होते हैं, decorators नहीं। `on_list_resources` हर `resources/list` request का जवाब देता है; जोड़ने का पूरा काम बस इतना ही है।
* हर paged handler का type `params: PaginatedRequestParams | None` होता है, और उदाहरण दोनों स्वीकार करता है। लेकिन किसी connection पर SDK आपको कभी `None` नहीं देता (बिना `params` member वाली request handler तक default values वाले model के रूप में पहुँचती है), इसलिए जो संकेत मायने रखता है वह है `params.cursor is None`: **शुरू से शुरू करें**।
* Cursor **क्या** है, यह आप तय करते हैं। यहाँ यह string के रूप में लिखा गया offset है। Timestamp, primary key, base64 blob: कुछ भी जिसे आप बाहर भेजते समय बना सकें और वापस आने पर पहचान सकें।
* `next_cursor=None` से आप कहते हैं "वह आख़िरी page था"। कोई count नहीं, कोई total नहीं, कोई `has_more` नहीं। `None` ही पूरा संकेत है।

!!! tip
    10 का `PAGE_SIZE` उदाहरण को पढ़ने लायक बनाता है। अपना page size हर endpoint के हिसाब से चुनें:
    एक-line वाले resources की list 500 का page झेल सकती है; भारी-भरकम prompt templates की list नहीं।
    इसमें client की कोई राय नहीं चलती, और यह जानबूझकर ऐसा है।

### इसे आज़माएँ {#try-it}

`Client(server)` memory में low-level `Server` से ठीक वैसे ही जुड़ता है जैसे `MCPServer` से।

बिना arguments के `list_resources()` call करें। आपको दस resources मिलते हैं, `book-1` से `book-10` तक, और `next_cursor` string `"10"` है।

इसे `list_resources(cursor="10")` से वापस दें, तो पहला resource `book-11` है और नया `next_cursor` `"20"` है।

दसवाँ page `next_cursor` को `None` पर set करके लौटता है। हो गया।

## Client loop {#the-client-loop}

`Client` का हर `list_*` method (`list_tools`, `list_resources`, `list_resource_templates`, `list_prompts`) `cursor=` keyword लेता है। Paged list को पूरा खींचना एक `while True` है:

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` `None` से शुरू होता है, इसलिए पहली request में कोई cursor नहीं जाता।
* `next_cursor` देखने से **पहले** extend करें: आख़िरी page में भी resources होते हैं।
* `next_cursor is None` ही बाहर निकलने का रास्ता है। बाकी कुछ भी सीधे `cursor=` में वापस जाता है, बिना छेड़े।

इसका `main()` चलाएँ और यह `100 resources` print करता है: दस-दस के दस pages, एक ऐसे loop से जुड़े हुए जिसे कभी पता ही नहीं था कि दस pages थे।

यह वही loop है जो **[The Client](../client/index.md)** हर `list_*` verb के लिए दिखाता है, और paging न करने वाले server पर इसकी कोई क़ीमत नहीं: पहले ही response में `next_cursor` `None` होता है और loop एक बार चलता है।

## तीन नियम {#the-three-rules}

**Cursors opaque होते हैं।** Client को कभी किसी cursor को parse करना, बनाना या अंदाज़ा लगाना नहीं चाहिए। Cursor का एकमात्र वैध स्रोत पिछले page का `next_cursor` है, जस का तस।

**Page size server चुनता है।** Protocol में कोई `limit=` नहीं है। अलग page size चाहिए तो server बदलें।

**Paging को नज़रअंदाज़ करने वाला client भी काम करता है।** वह एक बार `list_resources()` call करता है, पहले दस पाता है, और जिस `next_cursor` को उसने फेंक दिया उस पर कभी ध्यान नहीं देता। कुछ टूटता नहीं; उसे बस कम दिखता है।

!!! check
    Opaque का मतलब opaque। कोई cursor गढ़ लें (`list_resources(cursor="page-2")`) तो
    protocol आपके लिए कुछ नहीं कर सकता। यह server `int("page-2")` आज़माता है, handler raise करता है,
    और client के पास जो लौटता है वह है:

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    जो cursor आपको server से नहीं मिला, वह bug है, feature request नहीं।

## सारांश {#recap}

* `MCPServer` सब कुछ एक page में लौटाता है। Pagination opt-in है, और opt in आप low-level `Server` पर करते हैं।
* `on_list_resources` (और `on_list_tools`, `on_list_prompts`, `on_list_resource_templates`) को `PaginatedRequestParams | None` मिलता है; पहले page के लिए `params.cursor` `None` होता है।
* आप एक page और `next_cursor` लौटाते हैं: कोई भी string जिसे आप बाद में पहचान लें, या `None` जब कुछ बचा न हो।
* Client loop: `cursor=` दें, जमा करें, `next_cursor is None` होने तक दोहराएँ।
* Cursors opaque होते हैं, page size server का है, और paging न करने वाले client को भी पहला page मिलता है।

हाथ से लिखी `Server` API का बाकी हिस्सा (`on_call_tool`, `input_schema` dicts, `_meta`) **[The low-level Server](low-level-server.md)** में है।
