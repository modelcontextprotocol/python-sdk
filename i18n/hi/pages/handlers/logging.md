---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# Logging {#logging}

किसी tool से log वैसे ही करें जैसे किसी भी दूसरे Python function से करते हैं: standard library के साथ।

MCP में protocol स्तर की **logging capability** है: server अपने log messages को `Context` object के methods के ज़रिए notifications के रूप में client तक भेज सकता था। spec का 2026-07-28 revision **उस capability को deprecate करता है और उसकी जगह कुछ नहीं लाता**, इसलिए ये docs उसे नहीं सिखाते। क्या-क्या deprecated है और उसके बदले क्या करना है, इसकी पूरी सूची **[Deprecated features](../deprecated.md)** में है।

उसके बदले आप वही करते हैं जो हर दूसरे Python program में करते हैं: standard library।

## log करने वाला tool {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` आपको आपके module के नाम वाला logger देता है। इसे एक बार बनाएँ, सबसे ऊपर।
* tool के अंदर आप `logger.info(...)` को किसी भी दूसरे function की तरह call करते हैं। न कुछ inject करना है, न कुछ `await` करना है, न कुछ MCP-specific है।

!!! check
    tool को call करें और पूरा result देखें:

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    log line इसमें कहीं नहीं है। logging **आपके** लिए है, उस व्यक्ति के लिए जो server चला रहा है। model
    इसे कभी नहीं देखता। अगर model को कुछ पढ़ना चाहिए, तो उसे `return` करें।

## यह कहाँ जाता है {#where-it-goes}

**stdio** server के लिए यह सवाल आम से ज़्यादा मायने रखता है। host ने आपके server को subprocess के रूप में शुरू किया है और उसके **stdout** से MCP messages पढ़ रहा है। standard error आपका है।

standard library पहले से सही काम करती है: log output default रूप से `sys.stderr` पर जाता है। आपकी `logger.info(...)` lines terminal में पहुँचती हैं (या जहाँ भी host subprocess का stderr इकट्ठा करता है), और protocol stream साफ़ रहता है।

!!! tip
    stdio server में `print()` न करें। `print` **stdout** पर लिखता है, और stdout protocol का है।
    serve करते समय SDK उस stdout को stderr की ओर मोड़ देता है जो सच में **flush** हुआ हो, ताकि वह
    wire को खराब न कर सके, लेकिन block-buffered process में `print()` आमतौर पर `sys.stdout` के buffer में
    बिना flush हुए पड़ा रहता है, जब तक interpreter exit पर उसे खाली नहीं करता, सीधे protocol stream पर। जब उसे
    मोड़ा भी जाता है, तब भी वह line log output के बीच कच्ची ही पहुँचती है, बिना level के, बिना logger नाम के, और बिना उसे filter करने के किसी तरीके के।

    `logger.debug("got here")` उतनी ही एक line की मेहनत है और सही जगह जाता है।

## Level {#the-level}

आपको `logging.basicConfig()` खुद call करने की ज़रूरत नहीं है। `MCPServer` बनाते ही यह पहले से हो चुका है, standard error की ओर इशारा करते handler के साथ, उस level पर जो आप `log_level=` में देते हैं, इसलिए अपनी `logger.debug(...)` lines देखने के लिए `MCPServer("Bookshop", log_level="DEBUG")` ही काफ़ी है।

default `"INFO"` है।

`logging.basicConfig()` पहले से मौजूद handlers को कभी नहीं बदलता। अगर आप server बनाने से पहले खुद logging configure करते हैं, तो आपका configuration ही चलता है।

## इसे आज़माएँ {#try-it}

server को MCP Inspector के साथ चलाएँ:

```console
uv run mcp dev server.py
```

**Tools** tab से `search_books` को call करें। Inspector आपको result दिखाता है: सिर्फ़ return value। यह line

```text
Searching for 'dune'
```

standard error पर गई: terminal पर, wire पर नहीं।

!!! info
    अगर आपको असल में **tracing** चाहिए (हर request, उसमें कितना समय लगा, वह fail हुई या नहीं), तो आपको
    log lines नहीं, spans चाहिए। आपका server उन्हें पहले से भेजता है: SDK बिना कुछ configure किए हर
    message को OpenTelemetry से trace करता है। **[OpenTelemetry](../run/opentelemetry.md)** देखें।

## सारांश {#recap}

* MCP protocol की logging capability को 2026-07-28 spec deprecate करता है और उसकी जगह कुछ नहीं लाता। उस पर कुछ न बनाएँ।
* module स्तर पर `logger = logging.getLogger(__name__)`, tool में `logger.info(...)`। पूरा pattern बस इतना ही है।
* log output कभी model तक नहीं पहुँचता। सिर्फ़ वही value पहुँचती है जो आप `return` करते हैं।
* standard error आपका है; stdout protocol का है। serve करते समय SDK flush हुए भटके stdout को stderr की ओर मोड़ देता है, लेकिन बिना flush हुआ `print()` फिर भी exit पर wire पर खाली हो सकता है, और मोड़ी गई lines बिना label के पहुँचती हैं; `logging` इस्तेमाल करें, जिसका handler हर record को flush करता है।
* `MCPServer(..., log_level="DEBUG")` level तय करता है, और जो logging configuration आपने पहले बनाया हो उसे छेड़ा नहीं जाता।

जुड़े हुए clients को यह बताना कि आपके server पर कुछ बदला है (tool list, कोई resource), **[Subscriptions](subscriptions.md)** का विषय है।
