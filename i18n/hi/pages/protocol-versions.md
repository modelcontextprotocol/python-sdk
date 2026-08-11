---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# Protocol versions {#protocol-versions}

MCP की दो पीढ़ियाँ हैं।

2026-07-28 से पहले आए servers हर connection **`initialize` handshake** से खोलते हैं: client एक version सुझाता है, server अपना जवाब देता है, client उसे मान लेता है, और यह सब पहली काम की request से पहले होता है। **2026-07-28** वाले servers handshake छोड़ देते हैं। client एक **`server/discover`** probe भेजता है और server एक ही result में सब कुछ लौटा देता है।

आपको इसकी चिंता लगभग कभी नहीं करनी पड़ती, क्योंकि `Client` आपके लिए negotiate कर लेता है। यह page उस एक constructor argument के बारे में है जो इसे नियंत्रित करता है, `mode=`, और उन तीन मौकों के बारे में जब आप इसे बदलते हैं।

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

आपने `mode` नहीं दिया, इसलिए default मिला: `"auto"`। `async with` में दाख़िल होते ही इस SDK के सबसे नए version पर एक `server/discover` probe भेजा जाता है। फिर:

* **modern server** इसका जवाब देता है। client उस result को अपना लेता है। एक round trip, और काम ख़त्म।
* **पुराना server** `server/discover` को जानता ही नहीं और error लौटाता है। client पुराने classic `initialize` handshake पर लौट आता है और वह जो भी negotiate करे, उसे ले लेता है।

दोनों ही सूरतों में connection बन जाता है, और `client.protocol_version` बताता है कि कौन-सा रास्ता लिया गया:

```text
2026-07-28
```

पूरा feature बस इतना ही है। एक `Client`, किसी भी पीढ़ी का server, और code में कोई branching नहीं।

!!! info
    `MCPServer` हर transport पर `server/discover` का जवाब देता है — in-memory, stdio, streamable
    HTTP — इसलिए आपके अपने server के साथ `auto` हमेशा `2026-07-28` पर पहुँचता है। fallback सिर्फ़
    असली pre-2026 server के सामने ही चलता है, और ठीक वहीं आप इसे चाहते भी हैं।

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` कभी probe नहीं करता। यह `initialize` handshake चलाता है, वही connection जो pre-2026 client खोलता है।

```text
2025-11-25
```

server वही है। यह `2026-07-28` बख़ूबी बोलता है; आपने ही client से कहा कि वह न पूछे।

इसकी ज़रूरत **push-style** features के लिए पड़ती है।

server-initiated request का मतलब है server का **आपको** call करना: `ctx.elicit(...)` आपके user के सामने form रखता है, sampling tool call के बीच में आपके model से completion माँगती है। यह channel सिर्फ़ handshake पीढ़ी के session पर ही मौजूद होता है।

2026-07-28 पर यह channel नहीं रहा। server अपने सवाल **लौटाता** है और आप जवाबों के साथ call दोबारा करते हैं (**[Multi-round-trip requests](handlers/multi-round-trip.md)**)।

`mode="auto"` handshake तभी देता है जब server इतना पुराना हो कि और कुछ चले ही नहीं। `mode="legacy"` इसकी गारंटी देता है। जब भी आप `Client(...)` को `sampling_callback`, request के रूप में चलाया जाने वाला `elicitation_callback`, या `message_handler` देते हैं, इसे चुनें। **[Client callbacks](client/callbacks.md)** में हर एक की बात विस्तार से है।

## Version pin करना {#pinning-a-version}

`mode` modern protocol version string भी स्वीकार करता है। आज यह set ठीक `["2026-07-28"]` है।

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

pin **कुछ भी नहीं** भेजता। न probe, न handshake। client locally `2026-07-28` अपना लेता है और `async with` के लौटते ही connection चालू हो जाता है।

pin एक वादा है जो **आप** करते हैं: आपको पहले से पता है कि server वह version बोलता है। client जाँचता नहीं।

!!! check
    pin discovery नहीं है। `client.server_info` print करें और इसकी कीमत सामने दिख जाती है:

    ```text
    None
    ```

    client ने server से कभी पूछा ही नहीं कि वह कौन है, इसलिए `server_info` `None` है। `client.server_capabilities`
    का भी यही हाल है: हर capability `None` है। tool calls फिर भी काम करते हैं (protocol को इनमें से किसी की ज़रूरत नहीं);
    जो code यह तय करने के लिए `server_capabilities` पढ़ता है कि क्या पेश करना है, वह काम नहीं करता।

    अगला section इसका हल है।

सिर्फ़ modern versions ही pin किए जा सकते हैं। handshake पीढ़ी की string construction के समय ही, किसी भी I/O से पहले, ठुकरा दी जाती है, और error बताता है कि इसकी जगह क्या लिखना है:

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## `prior_discover` के साथ दोबारा connect करना {#reconnecting-with-prior_discover}

probe सस्ता है, लेकिन फिर भी यह एक round trip है जो हर reconnect पर चुकाना पड़ता है, और इसका जवाब लगभग कभी नहीं बदलता।

इसलिए इसे संभाल कर रखें। `auto` connection के बाद `client.session.discover_result` में ठीक वही `DiscoverResult` होता है जो server ने भेजा था: उसके `supported_versions`, उसकी `capabilities`, उसके `instructions`, और वह पहचान जो server ने result के `_meta` में दर्ज की थी। अगली बार इसे `prior_discover=` के रूप में वापस दें:

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

दूसरे connection ने negotiation का **एक भी** round trip नहीं किया और फिर भी ठीक-ठीक जानता है कि वह किससे बात कर रहा है। pinned mode का सही तरीका यही है: `mode=` version बताता है, `prior_discover=` पहचान देता है। ✨

`DiscoverResult` Pydantic model है। `saved.model_dump_json()` किसी file या cache में जाता है; `DiscoverResult.model_validate_json(...)` अगले process में इसे वापस ले आता है।

!!! tip
    `prior_discover=` तभी कुछ करता है जब `mode` version pin हो। `"auto"` में client
    वैसे भी server को probe करता है, और `"legacy"` में इसे नज़रअंदाज़ कर दिया जाता है।

## चार modes {#the-four-modes}

| आप लिखते हैं | Negotiation traffic | आपको मिलता है |
| --- | --- | --- |
| `Client(target)` | एक `server/discover` probe; वह नाकाम हो तो `initialize` handshake | सबसे नया version जो दोनों तरफ़ बोलते हैं, पीढ़ी कोई भी हो |
| `Client(target, mode="legacy")` | `initialize` handshake | handshake पीढ़ी का version; server-initiated requests काम करती हैं |
| `Client(target, mode="2026-07-28")` | कुछ नहीं | वही version, pinned, `server_info` `None` के साथ |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | कुछ नहीं | वही version, pinned, **और** वह पहचान जो आपने पिछली बार संभाली थी |

## सारांश {#recap}

* MCP की एक handshake पीढ़ी है (`2025-11-25` तक, `initialize` handshake) और एक modern पीढ़ी (`2026-07-28`, `server/discover`)। `Client` दोनों को जोड़ता है।
* `mode="auto"` default है: probe, फिर ज़रूरत पड़े तो fall back। इसे वैसे ही रहने दें, जब तक बाकी तीन rows में से कोई आप पर लागू न हो।
* "मुझे क्या मिला?" का जवाब हमेशा `client.protocol_version` है।
* `mode="legacy"` handshake ज़बरदस्ती करवाता है। server-initiated requests के लिए आपको यही चाहिए: sampling, push elicitation, `message_handler`।
* version pin (`mode="2026-07-28"`) negotiation traffic बिल्कुल नहीं भेजता, इसकी कीमत यह कि `client.server_info` `None` रहता है।
* `prior_discover=` वह कीमत लौटा देता है: `client.session.discover_result` संभाल कर रखें, उसी के साथ reconnect करें, दोनों पाएँ।

modern connection में push channel नहीं होता, तो 2026 पीढ़ी का server call के बीच में आपसे सवाल कैसे पूछे? वह उसे लौटा देता है: **[Multi-round-trip requests](handlers/multi-round-trip.md)**।
