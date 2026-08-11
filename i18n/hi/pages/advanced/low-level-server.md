---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# Low-level Server {#the-low-level-server}

`@mcp.tool()` एक layer है। इसके नीचे एक दूसरी server class है, `Server`, जो raw MCP बोलती है: आप इसे protocol objects देते हैं और यह उन्हें बिना बदले wire पर रख देती है।

`MCPServer` इसी के ऊपर बना है। नीचे आप तब उतरते हैं जब convenience layer रास्ते में आने लगे:

* आपको **हूबहू** कोई schema भेजना है (file से load किया हुआ, database से generate किया हुआ), न कि Python signature से निकाला गया।
* आपको result पर पूरा नियंत्रण चाहिए: `_meta`, `is_error`, `structured_content` की हर key।
* आपको ऐसा method handle करना है जिसे MCP define नहीं करता।

बाकी सब के लिए `MCPServer` पर ही रहें।

## वही tool, हाथ से {#the-same-tool-by-hand}

यह वही `search_books` tool है जिसे **[Tools](../servers/tools.md)** `@mcp.tool()` की नौ lines में लिखता है, बस sugar हटाकर:

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

तीन चीज़ें बदलीं, और पूरा low-level API बस यही है:

* **Handlers constructor parameters हैं।** `on_list_tools=` और `on_call_tool=` `Server(...)` में जाते हैं। यहाँ नीचे कोई decorator नहीं है, और हर handler का आकार एक ही है: `async (ctx, params) -> result`।
* **Input schema आप लिखते हैं।** `Tool.input_schema` एक सादा JSON Schema `dict` है। कोई इसे type hints से नहीं निकालता, क्योंकि निकालने के लिए type hints हैं ही नहीं।
* **Result आप बनाते हैं।** `CallToolResult(content=[TextContent(...)])`, हाथ से। न कुछ wrap होता है, न convert, न return annotation से अनुमान लगाया जाता है।

`params` parse की हुई request है: `CallToolRequestParams` आपको `.name` और `.arguments` देता है। `ctx` एक `ServerRequestContext` है: client से वापस बात करने के लिए `ctx.session`, `ctx.lifespan_context`, `ctx.request_id`, और `ctx.meta`, यानी request का आने वाला `_meta`।

!!! info
    अगर आपने FastAPI इस्तेमाल किया है, तो यह रिश्ता आप पहले से जानते हैं। `MCPServer` decorators और type hints वाली layer है; `Server` उसके नीचे का Starlette है। ये प्रतिद्वंद्वी नहीं हैं: `MCPServer` एक `Server` बनाता है और उस पर ठीक ऐसे ही handlers register करता है।

### इसे आज़माएँ {#try-it}

इसके लिए कोई Inspector नहीं है: `mcp dev` और `mcp run` सिर्फ़ `MCPServer` स्वीकार करते हैं। In-memory `Client` को कोई फ़र्क नहीं पड़ता; वह low-level `Server` को ठीक वैसे ही लेता है जैसे `MCPServer` को:

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

वही text जो `@mcp.tool()` वाले version ने दिया था। दो असली अंतर:

* `result.structured_content` `None` है। High-level server आपके लिए `-> str` को `{"result": ...}` में wrap कर देता है; यहाँ जो आपने नहीं बनाया, उसे कोई नहीं बनाता।
* `list_tools` वही schema लौटाता है जो **आपने** type किया, अक्षर-दर-अक्षर। High-level version में हर property पर `"title": "Query"` था और root पर `"title": "search_booksArguments"`: Pydantic की देन। यहाँ नीचे, अगर कुछ wire पर है, तो उसे वहाँ आपने रखा है।

## आपके लिए कुछ जाँचा नहीं जाता {#nothing-is-checked-for-you}

`MCPServer` गलत argument को आपका function चलने से पहले ही ठुकरा देता है, call को अपने generate किए schema से validate करके (**[Tools](../servers/tools.md)**)।

`Server` ऐसा नहीं करता। आपका `input_schema` client को **advertise** होता है; `params.arguments` पर कभी **लागू** नहीं होता।

!!! check
    `search_books` को बिना `limit` के call करें और आपका `args["limit"]` `KeyError` raise करता है। Client को दिखता है:

    ```text
    MCPError: Internal server error
    ```

    एक JSON-RPC error, code `-32603`, जान-बूझकर generic message के साथ: SDK आपका traceback किसी remote caller को leak नहीं करेगा। Model को कभी पता नहीं चलता कि उसने क्या गलत किया, इसलिए वह दोबारा कोशिश नहीं कर सकता। (Test में `raise_exceptions=True` इसके बजाय असली exception सामने लाता है; देखें **[Testing](../get-started/testing.md)**।)

यह बात हर जगह लागू होती है। Low-level handler से raise हुआ exception **हमेशा** protocol error होता है, कभी `is_error=True` वाला tool result नहीं। अगर आप चाहते हैं कि model failure पढ़े और संभल जाए, तो `params.arguments` खुद validate करें और `CallToolResult(content=[TextContent(...)], is_error=True)` लौटाएँ। Failure के ये दो प्रकार **[Errors संभालना](../servers/handling-errors.md)** का विषय हैं।

## दो tools, एक handler {#two-tools-one-handler}

`on_call_tool` server के हर tool के लिए अकेला entry point है। Routing आप `params.name` पर करते हैं:

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` दोनों advertise करता है। `call_tool` नाम के आधार पर dispatch करता है।
* `else` branch मायने रखती है: `Server` किसी ऐसे नाम के लिए आई `tools/call` को भी, जिसे आपने कभी list नहीं किया, सीधे आपके handler में भेज देगा। वहाँ raise करने से call ऊपर वाले `-32603` में ही बदल जाती है।

## Structured output, हाथ से {#structured-output-by-hand}

`Tool` पर `output_schema` declare करें और result पर `structured_content` रखें। दोनों आपके हैं:

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

इसे call करें और result में दोनों रूप आते हैं:

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

`_meta` block server की पहचान की मुहर है: SDK इसे 2026 पीढ़ी के हर result में जोड़ता है, constructor से लिए `version` के साथ (जो server कोई version set नहीं करता वह खाली string बताता है)। जिस server को अपनी पहचान नहीं बतानी है, वह middleware से यह key हटा सकता है, क्योंकि middleware जो results लौटाता है उनका मालिक वही है।

Server इन दोनों fields की कभी तुलना नहीं करता। इस SDK का `Client` करता है: ऐसा `structured_content` लौटाएँ जो आपके declare किए `output_schema` पर खरा न उतरे, और `call_tool` एक `RuntimeError` raise करता है जो `Invalid structured content returned by tool search_books` से शुरू होता है और आगे `jsonschema` की failure उद्धृत करता है। Schema का वादा करना सस्ता है; उसे निभाना आपकी ज़िम्मेदारी है। Return types और schemas की पूरी सीढ़ी **[Structured Output](../servers/structured-output.md)** में है।

## `_meta`: application के लिए, model के लिए नहीं {#\_meta-for-the-application-not-the-model}

`content` जवाब का वह हिस्सा है जिसे model पढ़ता है। `structured_content` वही जवाब typed data के रूप में है। `_meta` तीसरा channel है: ऐसा data जो result के साथ **client application** के लिए चलता है, जवाब का हिस्सा बने बिना।

इसे record IDs, trace IDs, ऐसी किसी भी चीज़ के लिए इस्तेमाल करें जिसकी ज़रूरत आपके UI को है और आपके prompt को नहीं:

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* आप इसे `_meta=` के रूप में बनाते हैं, जो wire वाला नाम है। Client इसे `result.meta` के रूप में वापस पढ़ता है।
* अपनी keys को namespace दें (`bookshop/record_ids`)। `io.modelcontextprotocol/*` keys protocol के लिए reserved हैं।

!!! warning
    `_meta` आपके और client application के बीच की convention है, इसकी guarantee नहीं कि model तक क्या
    पहुँचता है। क्या render करना है यह host तय करता है। Tool result के किसी भी हिस्से में कभी कोई secret न रखें।

## Capabilities आपके handlers से तय होती हैं {#capabilities-follow-your-handlers}

`Server` ठीक उन्हीं method families को advertise करता है जिनके लिए आपने उसे handlers दिए। ऊपर वाला `Bookshop` `on_list_tools` और `on_call_tool` pass करता है और कुछ नहीं, इसलिए इससे जुड़ने वाला client देखता है:

```json
{"tools": {"listChanged": false}}
```

न `resources`, न `prompts`: उनके पीछे कुछ है ही नहीं। `on_list_prompts` pass करें और `prompts` दिखने लगता है; `on_completion` pass करें और `completions` दिखने लगता है।

`MCPServer` हमेशा tools, resources और prompts advertise करता है, चाहे आपने कोई register किया हो या नहीं, क्योंकि उसके managers हमेशा मौजूद रहते हैं। यहाँ नीचे constructor call **ही** declaration है।

## Lifespan generic {#the-lifespan-generic}

`Server` उस type में generic है जो उसका lifespan yield करता है। इसे एक बार annotate करें और object जहाँ भी सामने आता है, typed होता है:

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* Lifespan एक `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]` है; `async` generator पर `@asynccontextmanager` आपको ठीक यही देता है।
* यह जो भी `yield` करता है वह `ctx.lifespan_context` बन जाता है, और चूँकि handlers `ServerRequestContext[Catalog]` से annotate हैं, `.search(...)` autocomplete होता है और type-check होता है।
* Server शुरू होने पर इसमें एक बार enter किया जाता है और रुकने पर एक बार exit। Startup, teardown, और इसी विचार का `MCPServer` वाला version **[Lifespan](../handlers/lifespan.md)** में हैं।

`lifespan=` के बिना `ctx.lifespan_context` एक खाली `dict` है।

## आपका अपना method {#a-method-of-your-own}

Constructor उन methods को cover करता है जिन्हें MCP define करता है। बाकी सब `add_request_handler` cover करता है:

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* पहला argument method string है। Notifications के लिए इसका जुड़वाँ है, `add_notification_handler`।
* `params_type` वह model है जिससे आने वाले `params` आपका handler चलने से **पहले** validate होते हैं, इसलिए custom methods को वह validation **मिलती** है जो tools को नहीं मिलती। `RequestParams` को subclass करें ताकि `_meta` field हर दूसरे method की तरह parse हो।
* Handler `BaseModel`, `dict`, या `None` लौटाता है। SDK इसे JSON-RPC result में serialise कर देता है।

एक बात साफ़-साफ़: high-level `Client` के पास सिर्फ़ उन्हीं methods के लिए verbs हैं जिन्हें MCP define करता है, इसलिए कोई `client.reindex()` नहीं है। Vendor method ऐसे peer के लिए है जो पहले से जानता है कि यह मौजूद है: ऐसा client जो आप खुद ship करते हैं, या आपकी कोई दूसरी service जो JSON-RPC बोलती है।

एक method जिस पर आप दावा नहीं कर सकते:

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

Handshake runner का है। `server/discover`, `ping`, और बाकी हर built-in को आप बदल सकते हैं।

!!! tip
    उस error में जिस `Server.middleware` का ज़िक्र है, वह **हर** आने वाले message को wrap करता है, `initialize` समेत। अगर आप किसी नए method का जवाब देने के बजाय traffic देखना या फिर से लिखना चाहते हैं, तो **[Middleware](middleware.md)** से शुरू करें।

## बाकी handlers {#the-other-handlers}

इनमें से हर एक ऐसा विचार है जिसकी शब्दावली अब आपके पास है; हर एक का अपना page है।

* `on_call_tool`, `on_get_prompt`, और `on_read_resource` अपने सामान्य result के बजाय `InputRequiredResult` लौटा सकते हैं, ताकि call रुक जाए और client से input माँगा जाए; देखें **[Multi-round-trip requests](../handlers/multi-round-trip.md)**। इस tier के मुताबिक, आपके लिए कुछ install नहीं होता: जहाँ `MCPServer` default रूप से `requestState` को seal करता है, वहीं यहाँ आपका set किया `request_state` ठीक वैसे ही wire पार करता है जैसा लिखा गया, जब तक आप `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` से opt in न करें: एक line (दोनों नाम `mcp.server.request_state` से import होते हैं) और ठीक वही sealing और verification मिलती है जो `MCPServer` करता है (**[`requestState` की सुरक्षा](../handlers/multi-round-trip.md#protecting-requeststate)**)।
* `on_list_resources`, `on_read_resource`, `on_list_prompts`, `on_get_prompt`, `on_completion` बाकी primitives के लिए वही `(ctx, params) -> result` आकार हैं।
* `on_subscriptions_listen` 2026-07-28 की `subscriptions/listen` stream serve करता है। `SubscriptionBus` के ऊपर बना `ListenHandler` pass करें और अपने बाकी handlers से bus पर events publish करें; पूरी रचना के लिए देखें **[Subscriptions](../handlers/subscriptions.md)**।
* `server.streamable_http_app()` वही Starlette app लौटाता है जो `MCPServer` का लौटाता है; इसे वैसे ही deploy करें जैसे **[अपना server चलाना](../run/index.md)** किसी भी दूसरे ASGI app को deploy करता है। यहाँ नीचे कोई `server.run(transport=...)` नहीं है: `server.run(read_stream, write_stream, server.create_initialization_options())` streams की एक जोड़ी पर एक connection चलाता है, और पूरी जानकारी बस वही एक line है।

## सारांश {#recap}

* Low-level `Server` अपने handlers `on_*` **constructor parameters** के रूप में लेता है; हर handler `async (ctx, params) -> result` है।
* `input_schema` dict आप लिखते हैं और `CallToolResult` आप बनाते हैं। आपके लिए न कुछ derive होता है, न wrap, न validate।
* Handler में exception `-32603` protocol error है। जिस tool error को model पढ़ सके, वह `is_error=True` वाला `CallToolResult` है जिसे **आप** लौटाते हैं।
* Result पर `_meta` client application के नाम है, model के नहीं।
* `Server[T]` उस चीज़ में generic है जो उसका lifespan yield करता है; `ctx.lifespan_context` एक typed `T` है।
* `add_request_handler(method, params_type, handler)` कोई भी method serve करता है। `initialize` reserved है।
* `Server` जो capabilities advertise करता है, वे इससे निकलती हैं कि आपने कौन से handlers register किए।

`Client(server)` ने दोनों servers के साथ एक जैसा बर्ताव किया क्योंकि वे एक ही protocol **हैं**, और यही असली बात है। इससे नीचे की अगली layer कोई class है ही नहीं: वह **[Middleware](middleware.md)** है।
