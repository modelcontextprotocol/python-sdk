---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# Media {#media}

tool सिर्फ़ text ही लौटा सके, ऐसा नहीं है।

SDK में binary results के लिए दो helpers (**`Image`** और **`Audio`**) हैं, और एक **`Icon`** type है जो client के UI में आपके server, tools, resources और prompts को एक चेहरा देता है।

## image लौटाना {#returning-an-image}

return type को `Image` से annotate करें, उसे किसी file की ओर point करें, और लौटा दें:

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` इन दोनों में से ठीक एक लेता है: `path` (पढ़ने के लिए file) या `data` (raw bytes)।
* client को जो MIME type दिखता है, उसका अंदाज़ा suffix से लगाया जाता है: `logo.png` को `image/png` बताया जाता है।
* यहाँ logos में कुछ खास नहीं है। `server.py` के बगल में रखी कोई भी PNG चलेगी: आपके code का render किया हुआ chart, कोई diagram, कोई photo।

`Image` SDK की सुविधा है, protocol type नहीं। wire पर आपकी return value एक **`ImageContent`** block बन जाती है (file के bytes base64-encoded, साथ में MIME type):

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

दो बातें ध्यान देने लायक हैं:

* `data` base64 है। आपने bytes को छुआ तक नहीं; SDK ने file पढ़ी और encoding की।
* `structured_content` `None` है। `Image` model के देखने के लिए content है, application के parse करने के लिए data नहीं: कोई output schema नहीं है। (इसकी तुलना **[Structured output](structured-output.md)** से करें, जहाँ return annotation **ही** schema है।)

!!! info
    `ImageContent` और `AudioContent` `mcp.types` में रहते हैं, ठीक उस `TextContent` के बगल में
    जो एक सादा `str` result बन जाता है (**[Tools](tools.md)**)। tool result content blocks की list होता है; दो binary
    किस्मों को बनाने का सबसे छोटा रास्ता `Image` और `Audio` हैं।

### इसे आज़माएँ {#try-it}

कोई भी PNG `server.py` के बगल में रखें, उसका नाम `logo.png` रखें, और चलाएँ:

```console
uv run mcp dev server.py
```

**Tools** tab खोलें और `logo` को call करें। result कोई string नहीं है: यह `image` content block है, और Inspector आपकी तस्वीर render करता है। disk पर रखी file से लेकर screen पर दिखते pixels तक, बीच का सारा काम SDK ने किया।

## audio लौटाना {#returning-audio}

`Audio` का आकार भी वही है। `logo.png` को जहाँ था वहीं रहने दें, और कोई भी WAV उसके बगल में `chime.wav` नाम से रख दें:

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

result एक **`AudioContent`** block है:

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

वही बात: अंदर disk पर रखी file जाती है, बाहर base64 और MIME type आते हैं, कोई output schema नहीं।

## bytes या file {#bytes-or-a-file}

दोनों helpers `path=` की जगह `data=` (raw bytes) भी लेते हैं। यह उन bytes के लिए है जो कभी अपनी किसी file से आए ही नहीं — कोई database column, कोई HTTP response, कुछ जो Pillow ने अभी-अभी बनाया:

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

`path=` के साथ कुछ declare करने की ज़रूरत नहीं: result बनते समय file पढ़ी जाती है, और MIME type का अंदाज़ा suffix से लगाया जाता है:

* `Image`: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`.
* `Audio`: `.wav`, `.mp3`, `.ogg`, `.flac`, `.aac`, `.m4a`.

जिस suffix को यह नहीं पहचानता, वह `application/octet-stream` पर लौट आता है।

!!! check
    `data=` के साथ कोई filename नहीं होता, इसलिए अंदाज़ा लगाने के लिए कुछ नहीं है। `format=` भूल जाएँ तो
    SDK default पर आ जाता है: images के लिए `image/png`, audio के लिए `audio/wav`। इस तरह
    MP3 bytes से `Audio` बनाएँ तो client को `mime_type="audio/wav"` बताया जाता है, और फिर
    वह ईमानदारी से उसे decode करने में नाकाम रहता है। जब `data=` दें, तो `format=` भी दें।

## Icons {#icons}

`Icon` metadata है, content नहीं। इसमें image नहीं होती; यह URI से किसी image की ओर इशारा करता है, और client उसे fetch करके आपके server के नाम, किसी tool, resource या prompt के बगल में दिखा सकता है।

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` ऐसा URI है जिसे client resolve कर सके: `https:`, या `data:` URI अगर आप icon को बिना किसी अतिरिक्त fetch के embed करना चाहें।
* `mime_type` और `sizes` (`"48x48"`, या scalable format के लिए `"any"`) से client सही icon चुन पाता है जब आप कई icons दें।
* `theme="light"` या `theme="dark"` किसी icon को एक colour scheme के लिए चिह्नित करता है।

यही `icons=[...]` keyword `MCPServer(...)`, `@mcp.tool()`, `@mcp.resource()` और `@mcp.prompt()` सब लेते हैं।

### client इन्हें कहाँ देखता है {#where-a-client-sees-them}

icons उसी चीज़ के साथ चलते हैं जिसे वे सजाते हैं। server के icons client के connect होने पर `client.server_info` पर आते हैं (2026 पीढ़ी के connections पर यह optional है, इसलिए पहले इसे narrow करें):

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

tool के icons `tools/list` से मिले `Tool` object पर होते हैं, resource के `resources/list` से मिले `Resource` पर, और prompt के `prompts/list` से मिले `Prompt` पर। field का नाम हमेशा `icons` होता है।

## सारांश {#recap}

* tool से `Image` या `Audio` लौटाएँ तो client को `ImageContent` / `AudioContent` block मिलता है: आपके bytes base64-encoded, MIME type के साथ।
* इसे `path=` से बनाएँ और suffix को MIME type तय करने दें, या in-memory `data=` और स्पष्ट `format=` से बनाएँ।
* media results में न `structured_content` होता है, न output schema।
* `Icon` एक pointer है: `src` URI और साथ में optional `mime_type`, `sizes` और `theme`।
* `icons=[...]` server पर, tools पर, resources पर और prompts पर काम करता है, और clients इन्हें संबंधित objects पर पाते हैं।

tool किसी result **में** जो कुछ डाल सकता है, वह सब यही है। जब tool **नाकाम** होता है तब क्या होता है (और किसे पता चलना चाहिए), यह **[errors संभालना](handling-errors.md)** में है।
