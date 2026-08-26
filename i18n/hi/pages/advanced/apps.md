---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

**MCP App** ऐसा tool है जिसका एक चेहरा है: अपने data के साथ-साथ tool एक HTML document की ओर इशारा करता है, जिसे host interactive surface के रूप में render करता है।

दो हिस्से, हमेशा दो हिस्से:

1. **एक tool**, जो काम करता है और data लौटाता है, किसी भी दूसरे tool की तरह।
2. **एक `ui://` resource**, जिसमें वह HTML है जो host उसके लिए दिखाता है।

tool में resource का `_meta.ui.resourceUri` reference होता है। host उसे `resources/read` से fetch करता है, **sandboxed iframe** में render करता है, और tool का result `postMessage` के ज़रिए उस iframe में भेजता है। आपका server कभी कोई `ui/*` message न भेजता है, न पाता है: वह traffic host और iframe के बीच का है। आप एक tool और एक HTML document serve करते हैं; दिखाने का सारा काम host करता है।

SDK इसे built-in `Apps` extension (`io.modelcontextprotocol/ui`) के रूप में देता है। अगर [Extensions](extensions.md) आपके लिए नए हैं, तो पहले उस page पर एक नज़र डाल लें। एक मिनट लगेगा, फिर वापस आएँ।

## चेहरे वाली घड़ी {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

चार कदम:

* `Apps()`: एक instance में आपके UI-bound tools और उनके resources रहते हैं।
* `@apps.tool(resource_uri="ui://clock/app.html")`: एक साधारण tool, साथ में
  `_meta.ui.resourceUri` की मुहर। जो कुछ `@mcp.tool()` लेता है (name, title,
  description, ...) वह सब यहाँ भी चलता है।
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`: उससे मेल खाता
  resource, जो `text/html;profile=mcp-app` के रूप में serve होता है। ठीक यही MIME type
  host को बताता है "यह app है, इसे render करें"।
* `MCPServer("clock", extensions=[apps])`: opt in करें। server अब
  `capabilities.extensions` के तहत `io.modelcontextprotocol/ui` advertise करता है।

HTML खुद host के `postMessage` को सुनता है और result दिखाता है। असली
apps के लिए अपने HTML के अंदर official [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps)
browser SDK इस्तेमाल करें। यह आपको raw message events की जगह `ontoolresult`, `callServerTool`,
`getHostContext` और `onhostcontextchanged` देता है।

## Graceful degradation {#graceful-degradation}

हर client apps render नहीं करता। इसका आपके लिए क्या मतलब है, spec साफ़-साफ़ कहता है:

> UI उपलब्ध होने पर भी tools का एक सार्थक `content` array लौटाना **अनिवार्य (MUST)** है।

model `content` पढ़ता है; iframe इंसानों के लिए है। UI-capable host भी text result
model को देता है, और text-only client को **सिर्फ़** वही मिलता है। इसलिए मानक
pattern है: एक tool, दो जवाब। `get_time` को फिर से देखें:

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

`client_supports_apps(ctx)` तभी `True` होता है जब client ने
`io.modelcontextprotocol/ui` extension declare किया हो **और** अपनी `mimeTypes`
settings में `text/html;profile=mcp-app` सूचीबद्ध किया हो। यह field ज़रूरी है,
इसलिए जो client इसे छोड़ देता है वह गिना नहीं जाता। इसी file में `main()` ठीक यही
declare करता है: negotiation का client वाला आधा हिस्सा, और rich जवाब वापस आता है।

!!! warning
    कभी भी `"[Rendered UI]"` जैसा placeholder अकेले content के रूप में न लौटाएँ।
    अगर fallback text बेकार है, तो tool हर text-only client के लिए और खुद model
    के लिए बेकार है। वह वाक्य लिखें।

## iframe को lock करना {#locking-the-iframe-down}

सुरक्षा metadata resource वाले हिस्से पर रहता है: iframe क्या load कर सकता है, उसे
कौन-सी browser permissions चाहिए, वह किस तरह frame होना चाहेगा:

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` और `permissions` **host से की गई requests** हैं, server का व्यवहार नहीं। host
इन्हीं से iframe की Content-Security-Policy और Permissions-Policy बनाता है, और
मना भी कर सकता है। अनुमति मिल ही गई, यह मानने के बजाय अपने JS में feature-detect करें।

`ResourceCsp`, एक-एक field करके (Python नाम, wire key, host उसके साथ क्या करता है):

| Python | Wire (`_meta.ui.csp`) | क्या नियंत्रित करता है |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`: `fetch`/XHR कहाँ जा सकते हैं |
| `resource_domains` | `resourceDomains` | `img-src`, `style-src`, ...: static assets |
| `frame_domains` | `frameDomains` | `frame-src`: nested iframes |
| `base_uri_domains` | `baseUriDomains` | `base-uri`: `<base>` किस ओर इशारा कर सकता है |

`ResourcePermissions`: हर field iframe के लिए एक browser permission माँगता है।

| Python | Wire (`_meta.ui.permissions`) |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP और permissions **resource** पर रहते हैं, tool पर कभी नहीं। spec के tool
    metadata में इनके लिए कोई जगह नहीं है, और hosts वहाँ इन्हें अनदेखा करते हैं। SDK इस
    गलती को लिखना ही नामुमकिन बना देता है: `@apps.tool()` में `csp` parameter है ही नहीं।

### Visibility {#visibility}

tool पर `visibility=["app"]` कहता है "यह iframe के लिए है, model के लिए नहीं":

* `"model"`: model इसे call कर सकता है।
* `"app"`: iframe इसे call कर सकता है (`callServerTool` के ज़रिए)।
* छोड़ दिया जाए: दोनों, जो default है।

Filtering **host का** काम है। आपका server app-only tools को `tools/list` में किसी भी
दूसरे tool की तरह सूचीबद्ध करता है; host उन्हें model से छिपाता है। server-side filter न करें।

## वे नियम जो SDK लागू करता है {#the-rules-the-sdk-enforces}

ये सब startup पर ही fail होते हैं, production में नहीं:

* जो `resource_uri` या resource URI `ui://...` नहीं है, वह decoration/registration
  के समय `ValueError` है।
* ऐसे URI से बँधा tool जिसका **कोई मेल खाता registered resource नहीं** है, तब `ValueError`
  है जब `MCPServer(extensions=[apps])` extension को consume करता है। ऐसा tool जो HTML
  advertise करे पर `resources/read` पर 404 दे, misconfiguration है, इसलिए server
  construct होने से मना कर देता है।
* `@apps.tool()` पर `meta={"ui": ...}` `ValueError` है। `_meta["ui"]` decorator का
  है; अपनी बात `resource_uri=` और `visibility=` से कहें। बाकी `meta=` keys
  साथ में आराम से merge हो जाती हैं।

आज न TypeScript ext-apps SDK इनमें से कुछ पकड़ता है, न FastMCP; हम चाहेंगे कि
आपको यह किसी host से पहले पता चल जाए।

## Inline HTML से आगे {#beyond-inline-html}

`add_html_resource` आम मामले को संभालता है: HTML की एक string। बाकी किसी भी चीज़ के लिए,
disk पर रखा HTML हो या generate किया गया content, resource खुद बनाएँ और सौंप दें:

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

जब resource कोई MIME type साफ़ तौर पर set नहीं करता, तो `add_resource`
`text/html;profile=mcp-app` MIME type भर देता है, और साफ़ तौर पर दिए गए बेमेल type को
reject कर देता है: किसी और MIME type वाला `ui://` resource ऐसा resource है जिसे कोई host render नहीं करेगा।

!!! tip
    क्या आप ऐसे pre-GA host के लिए बना रहे हैं जो अब भी deprecated flat
    `_meta["ui/resourceUri"]` key पढ़ता है? इसे खुद merge करें:
    `@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`।
    nested `ui` object ही spec वाला आकार है; flat key हटने वाली है।

## इसे चलता देखें {#see-it-run}

`examples/stories/` में `apps` story यही page एक चलाने लायक जोड़ी के रूप में है: UI-bound
clock tool वाला एक server, और एक client जो Apps negotiate करता है, tool का
`_meta.ui.resourceUri` पढ़ता है, HTML fetch करता है और tool को call करता है।

```bash
uv run python -m stories.apps.client
```
