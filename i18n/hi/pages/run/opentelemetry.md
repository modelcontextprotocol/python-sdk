---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

आपका server पहले से trace हो रहा है। आपको कुछ जोड़ने की ज़रूरत नहीं।

आप जो भी server बनाते हैं, वह अपने संभाले हर message के लिए एक [OpenTelemetry](https://opentelemetry.io/) span emit करता है। यह आपने नहीं लिखा, और न आप इसे import करते हैं। जिस पल आप `MCPServer(...)` call करते हैं, यह मौजूद होता है।

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

यह पूरा, traced server है। `search_books` को call करें और उसके लिए span बन जाता है। low-level `Server` के लिए भी यही सच है: tracing दोनों में मौजूद है।

## आपको क्या मिलता है {#what-you-get}

हर inbound message एक `SERVER` span बन जाता है, जिसका नाम method और उसके target पर रखा जाता है। तो `search_books` के लिए `tools/call` का span `tools/call search_books` होता है, और सिर्फ़ `tools/list` बस `tools/list` रहता है।

हर span में कुछ attributes होते हैं:

* `mcp.method.name` और `mcp.protocol.version`, हर span पर।
* `jsonrpc.request.id`, request पर (notification का कोई नहीं होता)।
* जो handler raise करता है, वह span status को error पर set कर देता है। `is_error=True` वाला tool result भी यही करता है।

और क्योंकि tool call को trace करना बहुत आम ज़रूरत है, `tools/call` spans OpenTelemetry की [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) का पालन करते हैं:

* `gen_ai.operation.name`, जो `"execute_tool"` पर set होता है।
* `gen_ai.tool.name`, जो call हो रहे tool के नाम पर set होता है।

इसी तर्ज़ पर `prompts/get` span को `gen_ai.prompt.name` मिलता है। list methods में कोई `gen_ai.*` keys नहीं होतीं, क्योंकि वहाँ नाम देने के लिए कुछ है ही नहीं।

!!! tip
    इन्हीं GenAI attributes की वजह से tracing UI आपके tool calls को उसी तरह group करती है जैसे किसी भी दूसरे agent के। यह grouping आपको मुफ़्त मिलती है, बिना किसी अतिरिक्त code के।

## जब तक आप न चाहें, इसकी कोई कीमत नहीं {#it-costs-nothing-until-you-want-it}

यही वह हिस्सा है जो "default रूप से चालू" को एक सहज default बनाता है।

SDK सिर्फ़ `opentelemetry-api` पर depend करता है, जो OpenTelemetry का हल्का आधा हिस्सा है। जब कोई SDK और कोई exporter install न हो, तो span बनाना no-op है। इसलिए आपका server अभी जो spans emit कर रहा है, उनकी कीमत लगभग कुछ भी नहीं, और कोई उन्हें इकट्ठा नहीं कर रहा।

जिस दिन आप उन्हें **देखना** चाहें, दूसरा आधा हिस्सा install करें और उसे कहीं point करें:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

exporter को OpenTelemetry के सामान्य तरीके से configure करें, और SDK जो spans चुपचाप बनाता आ रहा था, वे सब दिखने लगते हैं। आपका server code नहीं बदलता। एक line भी नहीं।

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) ऐसा ही एक backend है, और यह configuration आपके लिए कर देता है: `pip install logfire`, `logfire.configure()`, और आपके MCP spans live view में दिखने लगते हैं। यह OpenTelemetry पर बना है, इसलिए नीचे लिखी हर बात इस पर भी लागू होती है।

## wire पार करने वाले traces {#traces-that-cross-the-wire}

trace सबसे ज़्यादा काम का तब होता है जब वह request को client से लेकर server के अंदर तक, एक जुड़ी हुई तस्वीर में follow करे।

जब client और server दोनों SDK चला रहे हों, तो यह जुड़ाव अपने आप होता है। client request में [W3C trace context](https://www.w3.org/TR/trace-context/) inject करता है, और server उसे वापस पढ़ लेता है, इसलिए server span उसी trace में client span के नीचे nest हो जाता है। यही [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414) है, और यह आपको बिना माँगे मिलता है।

अगर inbound message में कोई trace context नहीं है, जैसे ऐसे client से आई request जो SDK नहीं है, तो server span बिल्कुल नया orphan trace शुरू करने के बजाय server पर जो भी span पहले से current है उसी का child बन जाता है।

## इसे बंद करना {#turning-it-off}

tracing एक middleware है, आपके server की सूची में पहला। अगर आप सच में ऐसा server चाहते हैं जो कोई span emit न करे, तो इसे हटा दें:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    उस import में आगे underscore है, और यह जानबूझकर है। class provisional है, ठीक वैसे ही जैसे [`Server.middleware`](../advanced/middleware.md) provisional है, इसलिए import path के बदलने की उम्मीद रखें। आपको इसकी ज़रूरत लगभग कभी नहीं पड़ती: जब कोई exporter install न हो तो spans मुफ़्त हैं, इसलिए आम जवाब यही है कि उन्हें चालू रहने दें और exporter install न करें।

## सारांश {#recap}

* हर `MCPServer` और हर low-level `Server` बिना कुछ configure किए हर inbound message पर एक `SERVER` span emit करता है। आप कुछ नहीं लिखते।
* spans में `mcp.method.name` और `mcp.protocol.version` होते हैं; `tools/call` और `prompts/get` में GenAI attributes भी होते हैं ताकि आपके tool calls किसी भी दूसरे agent की तरह group हों।
* जब तक आप OpenTelemetry SDK और exporter install नहीं करते, इसकी कोई कीमत नहीं, और फिर यह आपके server में बिना किसी बदलाव के दिखने लगता है।
* जब दोनों तरफ़ SDK चल रहा हो, तो client से server तक trace context अपने आप propagate होता है।

कोई request चलेगी भी या नहीं, यह **[Authorization](authorization.md)** तय करता है।
