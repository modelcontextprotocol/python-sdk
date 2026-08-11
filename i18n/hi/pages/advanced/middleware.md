---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# Middleware {#middleware}

**middleware** एक async function है जो server को मिलने वाले हर message को wrap करता है।

इसे आप `async (ctx, call_next)` के रूप में लिखते हैं और `server.middleware` में append करते हैं। पूरा API बस इतना ही है।

!!! warning
    middleware list source में **provisional** के रूप में चिह्नित है: इसका signature और semantics
    किसी 2.x minor release में बदल सकते हैं। इसका इस्तेमाल messages को **देखने** (timing, logging, tracing) और
    **अस्वीकार करने** के लिए करें; इसे वह नींव न बनाएँ जिस पर आपका server खड़ा हो।

`MCPServer` यह list construction के समय लेता है (`MCPServer(name, middleware=[...])`) और इसे
`mcp.middleware` के रूप में उपलब्ध कराता है; low-level `Server` वही list `server.middleware` के रूप में देता है। नीचे दिया गया
उदाहरण low-level `Server` इस्तेमाल करता है; अगर `Server(name, on_call_tool=...)` आपके लिए नया है, तो पहले
**[Low-level Server](low-level-server.md)** पढ़ें।

## Timing middleware {#a-timing-middleware}

एक server, एक tool, एक middleware जो log करता है कि हर message में कितना समय लगा:

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` वही `ServerRequestContext` है जो आपके handlers को मिलता है। `ctx.method` raw
  method string है; `ctx.params` raw params हैं, किसी भी validation से **पहले**।
* `call_next(ctx)` बाकी chain चलाता है: validation, handler lookup, आपका handler।
  जो उसने लौटाया वही लौटा दें, तो response जस का तस रहता है।
* `try`/`finally` जानबूझकर है: जो handler raise करता है उसका समय भी मापा जाता है, क्योंकि failure
  आपके middleware तक `call_next` से निकले exception के रूप में पहुँचती है।
* `server.middleware.append(...)` इसे register करता है। list outermost-first चलती है, इसलिए
  `middleware[0]` वह है जो wire के सबसे नज़दीक है।

### इसे आज़माएँ {#try-it}

client connect करें, tools की सूची लें, एक को call करें। आपके log में **तीन** lines हैं:

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

आपने दो calls किए और तीन lines मिलीं। पहली `server/discover` है: वह request जो
client ने connection तैयार करने के लिए भेजी, आपके कुछ माँगने से पहले।

यही असली बात है। middleware **हर** inbound message को wrap करता है:

* connection setup: `server/discover`, या legacy session पर `initialize` और `notifications/initialized`।
* हर request और हर notification। notification के लिए `ctx.request_id is None` होता है,
  `call_next(ctx)` `None` लौटाता है, और आप जो भी लौटाएँ वह फेंक दिया जाता है।
* वह method भी जिसके लिए server के पास कोई handler नहीं है: `call_next`
  `MCPError(-32601, "Method not found")` को client की ओर जाते हुए आपके middleware के **बीच से** raise करता है।

## इसके अंदर आप क्या कर सकते हैं {#what-you-can-do-inside-one}

इस क्रम में कि आपको कितना हिचकना चाहिए, कम से ज़्यादा की ओर:

* **देखें (Observe)।** समय मापें, गिनें, log करें। ऊपर वाला उदाहरण।
* **अस्वीकार करें (Refuse)।** `call_next(ctx)` call करने के **बजाय** `MCPError` raise करें और उस एक message का
  जवाब JSON-RPC error से दिया जाता है। connection बना रहता है; अगला message निकल जाता है। इसी तरह
  server हर caller के लिए `subscriptions/listen` को gate करता है:
  Subscriptions page पर **[यह तय करना कि कौन देख सकता है](../handlers/subscriptions.md#deciding-who-may-watch)**
  इसे चरण दर चरण समझाता है।
* **फिर से लिखें (Rewrite)।** `ctx` dataclass है: `await call_next(dataclasses.replace(ctx, params=...))`
  बाकी chain को client के भेजे params से अलग params देता है। `initialize` के साथ ऐसा कभी न करें:
  client को जो result वापस मिलता है वह आपके बदले हुए params से बनता है, लेकिन
  server अपनी connection state मूल wire params से commit करता है। दोनों पक्ष
  handshake इस असहमति के साथ पूरा कर सकते हैं कि उन्होंने क्या negotiate किया।
* **जवाब दें (Answer)।** `call_next(ctx)` call किए बिना result लौटाएँ और वह आपके response के रूप में client को
  जाता है। `call_next` आपको तैयार wire form देता है, और pipeline आप जो लौटाते हैं उसे कभी patch नहीं करता,
  इसलिए पूरा envelope आपका है: 2026 पीढ़ी के connection पर इसमें
  `serverInfo` का `_meta` stamp शामिल है, जिसे SDK handler results में जोड़ता है पर आपके results में नहीं।

!!! check
    `initialize` उन चीज़ों में से एक है जिन्हें middleware wrap करता है, और इसके लिए आपको मिलने वाला यह **एकमात्र** hook है।
    `add_request_handler` से इसे अपने हाथ में लेने की कोशिश करें तो SDK मना कर देता है:

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` inline संभाला जाता है: जब तक आपकी middleware chain लौट नहीं आती, server आगे कोई inbound
    message नहीं पढ़ता। इसलिए `initialize` संभालते समय server-to-client request (`ctx.session.send_request(...)`,
    कोई elicitation) को await करना **connection को deadlock कर देता है**: जिस
    response का आप इंतज़ार कर रहे हैं वह कभी पढ़ा ही नहीं जा सकता। fire-and-forget notifications ठीक हैं।

## वह एक middleware जो default रूप से चालू आता है {#the-one-middleware-that-ships-on-by-default}

SDK ठीक एक middleware साथ देता है, और वह पहले से आपके server की list में है: वह जो
हर message के लिए OpenTelemetry span emit करता है। आप इसे append नहीं करते, और ज़्यादातर समय
इसके बारे में सोचते भी नहीं। जब तक आप कोई exporter install नहीं करते यह no-op है, और इसका अपना page है:
**[OpenTelemetry](../run/opentelemetry.md)**।

!!! info
    अगर आपने ASGI middleware लिखा है, तो यह आकार आप पहले से जानते हैं। Starlette का
    `(scope, receive, send)` यहाँ `(ctx, call_next)` बन गया, और यह transport के **बाद** चलता है,
    raw HTTP request की जगह decoded message पर। दोनों साथ मिलकर काम करते हैं: `streamable_http_app()` पर
    Starlette middleware HTTP देखता है; यह MCP देखता है।

## सारांश {#recap}

* middleware `async (ctx, call_next) -> result` है, जिसे `MCPServer(middleware=[...])` के रूप में पास किया जाता है (या
  `mcp.middleware` में append किया जाता है), और low-level `Server` पर `server.middleware` में append किया जाता है।
* यह **हर** inbound message को wrap करता है (`server/discover`, `initialize`, requests, notifications,
  अनजान methods) और outermost-first चलता है।
* `ctx.request_id is None` से आप notification और request में फ़र्क करते हैं।
* एक message को अस्वीकार करने के लिए `call_next` call करने के बजाय raise करें; connection बचा रहता है।
* SDK का अपना OpenTelemetry tracing भी एक middleware है, जो पहले से list में है। देखें
  **[OpenTelemetry](../run/opentelemetry.md)**।
* पूरा surface provisional है। इससे देखें; इस पर निर्माण न करें।

request को wrap करने वाली हर चीज़ बस इतनी ही है। **[Authorization](../run/authorization.md)** वह है जो तय करता है कि request
को चलने दिया जाए भी या नहीं।
