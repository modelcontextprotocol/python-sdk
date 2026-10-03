---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# Resources {#resources}

**resource** वह data है जिसे आप application के पढ़ने के लिए expose करते हैं।

फ़र्क बस यही है। tool वह है जिसे call करने का फ़ैसला **model** करता है। resource वह है जिसे load करने का फ़ैसला **application** करता है (कोई config file, कोई record, कोई document) और फिर model के सामने context के रूप में रखता है।

किसी सादे Python function पर `@mcp.resource(uri)` लगाकर आप resource declare करते हैं।

## आपका पहला resource {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

इसका आकार बिल्कुल tool जैसा है, बस एक चीज़ और है: **URI**। resources के पते होते हैं, नाम नहीं। client `config://app` माँगता है, `get_config` कभी नहीं।

बाकी सब SDK अब भी function से ही पढ़ता है:

* **नाम** function का नाम है: `get_config`।
* client को दिखने वाला **description** docstring है।
* **content** वही है जो आप लौटाते हैं।

`resources/list` के दौरान client को यह मिलता है:

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

और जब client `config://app` पढ़ता है, तो आपका function चलता है और return value text के रूप में वापस आती है:

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    listing सस्ती है। आपका function `resources/list` के दौरान call **नहीं** होता, सिर्फ़
    `resources/read` के दौरान होता है, और वह भी सिर्फ़ उसी URI के लिए जो माँगा गया हो। हज़ार resources
    expose करें, कीमत सिर्फ़ उन्हीं की चुकानी पड़ती है जिन्हें कोई खोलता है।

### इसे आज़माएँ {#try-it}

server को MCP Inspector के साथ चलाएँ:

```console
uv run mcp dev server.py
```

यह जो URL print करता है उसे खोलें और **Resources** tab पर जाएँ। `config://app` अपने description के साथ सूची में है। उस पर click करें और Inspector उसे पढ़ लेता है: config की आपकी दोनों lines सामने हैं।

## Resource templates {#resource-templates}

हर record के लिए एक अलग URI बड़े पैमाने पर नहीं चलता। URI में एक **placeholder** रखें और function पर उससे मेल खाता parameter:

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

URI में `{user_id}`, function पर `user_id: str`। पूरा contract बस इतना ही है।

अब यह **resource template** है, और इसका ठिकाना बदल जाता है: यह `resources/list` छोड़ देता है और उसकी जगह `resources/templates/list` में दिखता है, पते के बजाय pattern के रूप में:

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

client placeholder भरता है और एक ठोस URI पढ़ता है: `users://42/profile`, `users://ada/profile`। एक ही function इन सबका जवाब देता है, और match हुई value `user_id` के रूप में pass की जाती है:

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

result में `uri` पर ध्यान दें। यह वही **ठोस** URI है जो client ने माँगा था, template नहीं।

!!! check
    placeholders और parameters का मेल खाना ज़रूरी है। function parameter का नाम बदलकर
    `user` कर दें जबकि URI में अब भी `{user_id}` लिखा हो, तो decorator **import time पर ही** मना कर देता है,
    किसी client के उसके पास पहुँचने से पहले:

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    ऐसा mismatch सिर्फ़ bug ही हो सकता है, इसलिए SDK mismatch के साथ server शुरू होने ही नहीं देता।

placeholder syntax [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570) है: कई segments वाली values के लिए `{+path}`, वैकल्पिक query parameters के लिए `{?q,lang}`, और भी बहुत कुछ। SDK निकाली गई values पर default रूप से path-safety जाँच भी लागू करता है। पूरा reference **[URI templates और path safety](uri-templates.md)** में देखें।

`get_user_profile` `Context` से annotate किया गया parameter भी ले सकता है। SDK उसे inject करता है और उसे कभी URI parameter नहीं मानता, और वह आपको क्या देता है यह **[Context](../handlers/context.md)** page बताता है।

## आप क्या लौटाते हैं {#what-you-return}

आप `str` तक सीमित नहीं हैं। हर resource को `mime_type` दें और जो सही बैठे वह लौटाएँ:

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` `str` लौटाता है, इसलिए वह जस का तस भेजा जाता है। यही आम मामला है।
* `catalog_stats` `dict` लौटाता है, इसलिए SDK उसे आपके लिए **JSON text** में serialise कर देता है:

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` `bytes` लौटाता है, इसलिए client को `TextResourceContents` की जगह `BlobResourceContents` मिलता है, जिसके `blob` field में आपके bytes base64-encoded होते हैं।

यही नियम हर उस चीज़ पर लागू होता है जो JSON-serialisable है: list, Pydantic model, dataclass। अगर वह `str` नहीं है और `bytes` नहीं है, तो वह JSON बन जाता है।

`mime_type` declare करना आपका काम है, और इसका default `text/plain` है। इसका अंदाज़ा लगाने के लिए SDK कभी यह नहीं जाँचता कि आप क्या लौटाते हैं, इसलिए जिस `dict` resource पर आप label नहीं लगाते वह अब भी plain text के रूप में ही advertise होता है।

!!! tip
    जब आप इन्हें function से derive नहीं करना चाहते, तब `@mcp.resource()` `name=`, `title=` और `description=` भी
    स्वीकार करता है। और जब लिखने को कोई function ही न हो, तब
    `mcp.server.mcpserver.resources` में तैयार `Resource` classes हैं (`TextResource`,
    `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`) जिन्हें आप
    `mcp.add_resource(...)` से register करते हैं।

client किसी resource को **subscribe** भी कर सकता है और उसके बदलने पर notification पा सकता है; यह कहानी का client वाला हिस्सा है और **[Client](../client/index.md)** में है।

## सारांश {#recap}

* function पर `@mcp.resource(uri)` उसे resource बना देता है। URI पता है, return value content है, docstring description है।
* URI में `{placeholder}` उसे **template** बना देता है: यह `resources/templates/list` के तहत list होता है और एक ही function हर मेल खाते URI को serve करता है।
* placeholder के नाम function के parameter नामों के बराबर होने चाहिए। गलती करें तो पता import time पर चलता है, production में नहीं।
* आपका function तब चलता है जब resource **पढ़ा** जाता है, तब नहीं जब उसे list किया जाता है।
* `str` text बनता है, `bytes` base64 blob बनता है, बाकी सब JSON text बनता है। label आप `mime_type=` से लगाते हैं।
* tools model के काम करने के लिए हैं। resources application के पढ़ने के लिए हैं।

तीसरा primitive, जिसे कोई इंसान menu से चुनता है, **[Prompts](prompts.md)** है।
