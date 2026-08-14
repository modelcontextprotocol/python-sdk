---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# v2 में नया क्या है {#whats-new-in-v2}

v2 में दो चीज़ें एक साथ हुईं। **SDK को दोबारा बनाया गया**: client और server दोनों के नीचे नया engine, एक first-class `Client`, और कुछ renames जिनसे v1 codebase का सामना पहले import पर ही हो जाता है। और **protocol आगे बढ़ा**: v2 MCP का 2026-07-28 revision बोलता है, जो connection handshake, session और हर server-initiated request को हटा देता है, वह भी आपके मौजूदा clients को बीच में छोड़े बिना।

यह page दोनों हिस्सों का tour है, हर headline के लिए एक section, और हर section उस page पर खत्म होता है जो उस विषय का मालिक है। यह porting manual नहीं है। वह **[Migration Guide](migration.md)** है: हर breaking change, पहले और बाद के code के साथ।

!!! note "v2 ही stable line है"
    `pip install mcp` 2.x install करता है, और **[Installation](get-started/installation.md)** में
    copy-paste करने लायक install line है। अगर v2 में कुछ टूटता है, चौंकाता है, या आपकी रफ़्तार धीमी करता है, तो
    [हमें बताएँ](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)।

## SDK: v1 से v2 {#the-sdk-v1-to-v2}

### `FastMCP` अब `MCPServer` है {#fastmcp-is-now-mcpserver}

High-level server class का नाम बदला, और उसके module का भी। हर v1 server सबसे पहले इसी से टकराता है, क्योंकि पुराना import path deprecated नहीं, बल्कि हटा दिया गया है:

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

Decorator से बने server के लिए port का ज़्यादातर हिस्सा भी बस यही है। `@mcp.tool()`, `@mcp.resource()` और `@mcp.prompt()` वही स्वीकार करते हैं जो v1 में करते थे (`@mcp.resource()` में एक optional `security=` keyword जुड़ा है), और input schema अब भी आपके type hints से आता है। किनारों पर: `mcp.server.fastmcp.*` के नीचे की हर चीज़ अब `mcp.server.mcpserver.*` के नीचे रहती है, `ctx.fastmcp` अब `ctx.mcp_server` है, `get_context()` हटा दिया गया है (उसकी जगह `ctx: Context` parameter declare करें), और exception base `FastMCPError` अब `MCPServerError` है। Import table **[Migration Guide](migration.md#fastmcp-renamed-to-mcpserver)** में है।

### `Resolve`: user से input माँगने का नया तरीका {#resolve-the-new-way-to-ask-the-user-for-input}

Tool को जो कुछ चाहिए, वह सब model से नहीं आना चाहिए। v2 में नया: `Resolve(fn)` से annotate किया गया tool parameter model के बजाय आपके लिखे function से भरा जाता है, model को इसकी भनक तक नहीं लगती, और वह function user के सामने सवाल रखने के लिए `Elicit(...)` लौटा सकता है। Call के बीच client से कुछ भी पाने का यही पसंदीदा तरीका है: SDK सवाल को उसी mechanism पर ले जाता है जिसे connection support करता है (legacy client के लिए live elicitation request, 2026-07-28 पर multi-round-trip), इसलिए एक ही tool body दोनों पीढ़ियों को serve करती है। इसका page **[Dependencies](handlers/dependencies.md)** है।

!!! note
    बाकी दो रूप ज़रूरत पड़ने पर अब भी मौजूद हैं: legacy connections पर clients के लिए `ctx.elicit()` अब भी काम करता है
    (**[Elicitation](handlers/elicitation.md)**), और handler खुद `InputRequiredResult` लौटाकर
    rounds को हाथ से चला सकता है, और 2026-07-28 पर sampling और roots requests भी इसी रास्ते से जाती हैं
    (**[Multi-round-trip requests](handlers/multi-round-trip.md)**)।

### एक first-class `Client` {#a-first-class-client}

v1 आपको तीन nested परतें थमाता था: raw streams देने वाला transport context manager, उनके चारों ओर लिपटा `ClientSession`, और हाथ से call किया जाने वाला `await session.initialize()`। v2 में एक ही object है:

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` एक server object लेता है (in memory, कोई transport नहीं: testing की कहानी), एक URL (Streamable HTTP), या कोई भी transport context manager जैसे `stdio_client(...)`। `async with` में प्रवेश करते ही connect होता है और protocol version negotiate होता है, server चाहे जिस पीढ़ी का हो; उसके बाद `client.server_capabilities` और `client.protocol_version` बस उपलब्ध रहते हैं, और जब server अपनी पहचान बताता है तो `client.server_info` भी (यह अब `Implementation | None` है, क्योंकि 2026 पीढ़ी में identity optional है)। v1 में register किए गए sampling और elicitation callbacks अब भी काम करते हैं (उनकी bodies में वही snake_case attribute rename दिखता है जो इस page की हर चीज़ में), वे अब 2026-style requests-inside-results (नीचे) का जवाब भी देते हैं, और वे एक-एक करके नहीं, बल्कि concurrently चलते हैं। जिसे low-level surface चाहिए, उसके लिए `ClientSession` अब भी नीचे मौजूद है, और `client.session` उसे आपको देता है; वह भी बदला है (वह नए dispatcher engine पर चलता है, और उसके कुछ अपने signatures बदले हैं), इसलिए नीचे उतरने से पहले **[Migration Guide](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)** पढ़ें।

**[The Client](client/index.md)** इसका परिचय देता है, **[Client transports](client/transports.md)** connection के तीनों रूप समझाता है, **[Client callbacks](client/callbacks.md)** खुद callbacks को, और **[Testing](get-started/testing.md)** वह in-memory pattern दिखाता है जो v1 के `create_connected_server_and_client_session()` helper की जगह लेता है।

### Low-level `Server` का नाम नहीं बदला, उसे दोबारा बनाया गया {#the-low-level-server-was-rebuilt-not-renamed}

अगर आप JSON-RPC layer पर काम करते हैं, तो v2 का "सब कुछ अलग है" वाला हिस्सा यही है। यहाँ वही one-tool server दोनों तरह से है; क्या बदला, यह देखने के लिए markers पर click करें।

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. Handlers decorators से register होते हैं (call किए गए, parentheses के साथ), server बनने के बाद कभी भी।
2. आप bare `list[Tool]` लौटाते हैं और SDK उसे `ListToolsResult` में लपेट देता है।
3. Python में fields camelCase हैं, और schema **enforce होता है**: SDK आपके function के चलने से पहले `call_tool` arguments को इसके सामने jsonschema-validate करता है, इसीलिए नीचे `arguments["query"]` सुरक्षित है।
4. एक ही `call_tool` handler हर tool को serve करता है, और उसे tool का नाम और पहले से validate किए हुए arguments मिलते हैं, unpack किए हुए और कभी `None` नहीं।
5. v1 tool failure का संकेत raise करके देता है: कोई भी exception पकड़ा जाता है और `CallToolResult(isError=True)` के रूप में लौटाया जाता है, text में `str(e)` के साथ, इसलिए call करने वाला model यह message पढ़ता है और retry कर सकता है।
6. Context एक ambient ContextVar से आता है, जिस तक request के बीच server object के ज़रिए पहुँचा जाता है।
7. Bare content blocks आपके लिए `CallToolResult` में लपेट दिए जाते हैं।

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. Fields अब snake_case हैं, और schema **advertise होता है, पर कभी apply नहीं होता**: आपके handler के चलने से पहले arguments को कोई नहीं जाँचता।
2. हर handler का आकार एक जैसा है: `async (ctx, params) -> result`। Context पहला argument है (`ctx.session`, `ctx.request_id`, `ctx.protocol_version` इसी पर रहते हैं); `server.request_context` यहीं गया।
3. पूरा `ListToolsResult` आप खुद बनाते हैं। Bare list लौटाना अब server-side `TypeError` है, SDK उसे लपेटता नहीं।
4. Typed params अंदर (`params.name`, `params.arguments`), पूरा result बाहर। आपके लिए कुछ भी unpack, wrap या convert नहीं किया जाता।
5. वही जाँच, अलग verb। यहाँ `ValueError` model तक एक opaque `-32603` बनकर पहुँचता (नीचे देखें), इसलिए जानबूझकर भेजा जाने वाला wire error `MCPError` के रूप में raise किया जाता है: वह अपने code और message के साथ जस का तस निकल जाता है, और unknown tool के लिए इस text के साथ `-32602` spec का अपना जवाब है।
6. `params.arguments` `None` हो सकता है; v1 इसे आपके code तक पहुँचने से पहले ही `{}` कर देता था। Handler के सामने कोई validation न होने से यह line ज़रूरी है।
7. यहाँ raise हुआ कोई अनपेक्षित exception एक **sanitized** protocol error बनता है, `-32603` `"Internal server error"`: model को message कभी नहीं दिखता। ऐसे failure के लिए जिसे model पढ़े और उस पर प्रतिक्रिया दे, `CallToolResult(is_error=True, ...)` लौटाएँ।
8. Handlers constructor arguments हैं, इसलिए server बनते ही उसकी surface पूरी हो जाती है; `add_request_handler()` construction के बाद का escape hatch है, और custom methods का दरवाज़ा भी।

यह उदाहरण ही pattern है। और आम तौर पर: हर handler का आकार एक जैसा है, typed params अंदर और पूरा result type बाहर; tool arguments की पुरानी jsonschema जाँच हट गई है; exception एक protocol error है, कभी `is_error=True` tool result नहीं; और ambient `server.request_context` ContextVar हट गया है। Custom, vendor-namespaced methods `add_request_handler(method, params_type, handler)` के ज़रिए first class हैं, जो आपके handler के चलने से पहले inbound params को आपके model के सामने validate करता है। और एक `middleware` list (जानबूझकर provisional चिह्नित) हर inbound message को लपेटती है, उन private `_handle_*` methods की जगह जिन्हें लोग override किया करते थे।

अंदर ही अंदर, v1 के `BaseSession` receive loop की जगह एक dispatcher engine ने ली है जिसे अब client और server दोनों साझा करते हैं, और इसी की वजह से इस page की कई बातें एक साथ सच हैं: एक ही `Server` object दोनों protocol पीढ़ियों को serve करता है, `Client(server)` बिना JSON-RPC framing के in process dispatch करता है, और timed-out client request अब वाकई server-side handler को cancel करती है।

इसका page **[The low-level Server](advanced/low-level-server.md)** है; **[Migration Guide](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** हर हटाए गए hook से गुज़रता है। अगर आप कभी `MCPServer` से नीचे नहीं उतरे, तो इनमें से कुछ भी आपको नहीं छूता।

### Wire types `mcp-types` में चले गए, और हर field snake_case है {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

Protocol types अब अपने अलग distribution, `mcp-types`, में रहते हैं। यह pydantic और typing-extensions के सिवा किसी पर निर्भर नहीं है, इसलिए कोई gateway, proxy या code generator बिना HTTP stack install किए MCP के wire shapes इस्तेमाल कर सकता है: ऐसा project `mcp-types` install करता है और `mcp_types` import करता है। खुद `mcp` उस package पर exact version के साथ निर्भर है और उसे दोबारा expose करता है, इसलिए SDK पर निर्भर code पहले की तरह `import mcp.types as types` और `from mcp.types import Tool` लिखता रहता है (एक स्थायी alias, हर नाम वही object) और सिर्फ़ अपनी एक असली dependency, `mcp`, declare करता है। मोटा नियम: जिस package पर आप वाकई निर्भर हैं, उसी से import करें।

उन types पर हर Python attribute अब snake_case है: `result.is_error`, `tool.input_schema`, `listing.next_cursor`। Wire पर जाने वाला JSON camelCase है, बिल्कुल पहले जैसा; सिर्फ़ attribute की spelling बदली है। दो और सख्त defaults साथ आते हैं: unknown fields round-trip होने के बजाय ignore किए जाते हैं (extras `_meta` में रखें), और दोनों पक्ष traffic को उस protocol version के सामने validate करते हैं जो उन्होंने negotiate किया। Rename table के लिए **[Migration Guide](migration.md#field-names-changed-from-camelcase-to-snake_case)** देखें।

### Transport configuration `run()` में चली गई {#transport-configuration-moved-to-run}

`MCPServer(...)` इस बारे में है कि आपका server **क्या है**: उसका नाम, उसके instructions, उसका lifespan, उसका auth। उसे **serve कैसे** किया जाता है, यह अब `run()` और app builders का काम है, और `host`, `port`, `stateless_http`, `json_response`, endpoint paths और `transport_security` वहीं गए (`MCPServer("x", port=9000)` अब `TypeError` है)। Overloads हर transport के लिए typed हैं, इसलिए आपका editor बताता है कि `stdio` कौन से options लेता है और `streamable-http` कौन से। एक हटाव जानने लायक है: `mount_path` हट गया है; prefix के नीचे serve करने का supported तरीका ASGI app को mount करना है।

Options के लिए **[अपना server चलाना](run/index.md)** देखें; mounting के लिए **[मौजूदा app में जोड़ना](run/asgi.md)**।

### बिना import error के बदलने वाला व्यवहार {#behavior-that-changes-without-an-import-error}

Renames खुद अपनी घोषणा करते हैं। ये नहीं करते:

* **Sync functions worker thread पर चलते हैं।** `def` tool (या resource, prompt, या resolver) अब event loop को block नहीं करता; बदले में उसकी body अब event-loop thread **पर** नहीं चलती, जो thread-affine code के लिए मायने रखता है। `async def` handlers अछूते हैं। **[Migration Guide](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**।
* **Tool के अंदर raise हुआ `MCPError` (v1 का `McpError`) अब protocol error है।** Model उसे कभी नहीं देखता। बाकी हर exception अब भी `is_error=True` result बनता है जिसे model पढ़ सकता है और उस पर प्रतिक्रिया दे सकता है। यह विभाजन **[Errors संभालना](servers/handling-errors.md)** में है।
* **Results निकलने से पहले validate होते हैं।** हाथ से बना `Tool` जिसका `input_schema` `{}` है, अब `tools/list` में fail होता है (spec को `"type": "object"` चाहिए)। `@mcp.tool()` पर बने servers को यह कभी नहीं दिखता; उनके schemas SDK लिखता है।
* **आपका client जो पाता है उसे validate करता है।** `list_tools()` और `call_tool()` server के जवाब को negotiated protocol version के सामने जाँचते हैं, इसलिए पूरी तरह valid न रहने वाला server, जिसे v1 का ढीला parse सह लेता था, अब `pydantic.ValidationError` raise करता है। अगर आप ऐसे servers से connect करते हैं जो आपके नियंत्रण में नहीं हैं, तो मानकर चलें कि उन्हें खोजने वाले आप ही होंगे; ब्योरा **[Migration Guide](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)** में है।
* **URI templates अब असली RFC 6570 हैं।** `{+path}`, `{?query}` वगैरह काम करते हैं, matching regex-loose के बजाय exact है, और निकाली गई values में path traversal default रूप से reject होता है। ज़्यादा सख्त templates decoration के समय fail होते हैं, पहली request पर नहीं। **[URI templates](servers/uri-templates.md)**।
* **Streamable HTTP lifespan एक बार चलता है**, startup पर, और उसका state हर session और request के बीच साझा होता है। v1 में यह हर session पर एक बार चलता था, और `stateless_http=True` के तहत हर request पर एक बार। Lifespan में बने pools और caches बहुत सस्ते हो जाते हैं; जो कुछ वहाँ per-connection resource लेता था, वह अब handler body में होना चाहिए। **[Lifespan](handlers/lifespan.md)**।
* **`mcp dev` और `mcp install` जो environment spawn करते हैं उसे** आपके installed SDK version पर pin करते हैं। दोनों commands आपके server को नए `uv run --with ...` environment में चलाते हैं, जो पहले `mcp` को उस version के बजाय newest stable release पर resolve करता था जिसके सामने आप develop कर रहे हैं। **[Migration Guide](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**।
* **HTTP client अब `httpx` नहीं, `httpx2` है।** Dependency बदलने से यह बदलता है कि आपका code क्या catch करता और pass करता है (`httpx2.AsyncClient`, `httpx2.ConnectError`), और यह भी कि TLS certificates कैसे verify होते हैं: `httpx2` certifi की bundled CA list के बजाय `truststore` के ज़रिए operating system trust store के सामने validate करता है। ज़्यादातर environments को पता भी नहीं चलता; बिना system CA store वाला minimal container, या ऐसा private CA जिसे सिर्फ़ certifi का bundle जानता था, TLS handshake fail करने लगता है। `SSL_CERT_FILE`/`SSL_CERT_DIR` set करें या अपने client को `verify=ssl_context` pass करें। **[Migration Guide](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**।

### पूरी तरह हटाए गए {#removed-outright}

इनमें से हर एक **[Migration Guide](migration.md)** में एक section है:

* **WebSocket transport**, दोनों तरफ़, और `mcp[ws]` extra। यह कभी MCP specification का हिस्सा नहीं था।
* **Experimental Tasks** API (`mcp.*.experimental`)। 2026-07-28 tasks को core protocol से निकालकर एक official extension में ले जाता है ([SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)), जिसे यह SDK अभी implement नहीं करता।
* Import paths के रूप में `mcp.shared.version`, `mcp.shared.progress` और `mcp.shared.session` (उस `RequestResponder` stub के साथ जिसे v1 के `message_handler` annotations import करते थे)। (`mcp.types` हटाया **नहीं** गया है: यह standalone `mcp_types` package के स्थायी alias के रूप में बना रहता है।)
* Deprecated `streamablehttp_client` spelling, और `streamable_http_client` से `get_session_id` callback (जो अब ठीक दो streams देता है)।
* `McpError`, जिसका नाम बदलकर **`MCPError`** हुआ, सीधे `(code, message, data)` constructor के साथ।
* `MCPServer.get_context()`, `mount_path=`, और lowlevel `Server` के decorator methods, ContextVar और handler dicts।

## Protocol: 2025-11-25 से 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

v2 2026-07-28 revision implement करता है, और यह **दोनों** revisions एक साथ serve करता है: वही `streamable_http_app()` (और वही stdio server) 2025 पीढ़ी के client के `initialize` और 2026 पीढ़ी के client की requests, दोनों का जवाब देता है, बिना कुछ configure किए, बिना कोई flag पलटे, और बिना अलग deployment के। नया revision serve करने से पुराने revision वाला client बीच में नहीं छूटता। आगे वह है जो नया revision खुद बदलता है।

### न handshake, न session {#no-handshake-no-session}

2026-07-28 client connection खोलकर, negotiate करके, फिर बात नहीं करता। हर request अपना protocol version, client info और client capabilities `_meta` में साथ ले जाती है, और इकलौती discovery call, `server/discover`, किसी भी दूसरी request जैसी सादी request है। `Client` default रूप से सही काम करता है: वह एक बार `server/discover` probe करता है और अगर server पुराना है तो `initialize` handshake पर लौट आता है।

Streamable HTTP पर 2026 path में कोई `Mcp-Session-Id` नहीं है, और operational headline यही है: **कोई चीज़ modern request को किसी worker से नहीं बाँधती**, इसलिए सादे round-robin load balancer के पीछे कोई भी replica उसका जवाब दे सकता है। दो ईमानदार शर्तें। आपके 2025 पीढ़ी के clients (आज ज़्यादातर clients यही हैं) अब भी sessions खोलते हैं और उन्हें अब भी वही stickiness चाहिए जो v1 पर चाहिए थी; उनके लिए कुछ नहीं बदलता। और एक चीज़ जो **multi-round-trip** retry को workers के पार ले जानी होती है, वह उसका sealed `request_state` है, जिसकी default key हर process में अलग बनती है, इसलिए scaled-out deployment `RequestStateSecurity(keys=[...])` pass करता है। (`stateless_http=True` का इससे लेना-देना नहीं: वह सिर्फ़ यह तय करता है कि 2025 पीढ़ी के clients कैसे serve हों, और 2026 traffic उसे कभी नहीं पढ़ता; अगर आपने v1 में उसे पहले से set किया है, तो कुछ नहीं बदलता।)

इसका client वाला पहलू **[Protocol versions](protocol-versions.md)** है, operator की checklist **[Deploy & scale](run/deploy.md)** है (Host allowlist, `request_state` key, replicas के पार notifications), और दोनों पीढ़ियाँ एक साथ serve करने की कहानी **[Legacy clients को serve करना](run/legacy-clients.md)** है।

### Server client को call नहीं कर सकता: multi-round-trip requests {#the-server-cannot-call-the-client-multi-round-trip-requests}

2026-07-28 पर हर server-initiated request हट गई है: push elicitation, sampling, `roots/list`। 2026 connection पर उनके लिए कोई channel नहीं है, इसलिए `ctx.elicit()` और `ctx.session.create_message()` वहाँ `NoBackChannelError` के साथ fail होते हैं (legacy clients के लिए वे अब भी काम करते हैं)।

इसका विकल्प call को पलट देता है। जिस tool को user से कुछ चाहिए, वह सवाल **लौटाता** है (`InputRequiredResult`), client उन्हीं callbacks से उसका जवाब देता है जो उसके पास हमेशा से थे, और call को जवाबों के साथ retry किया जाता है। `Client` यह loop आपके लिए चलाता है। Server पर आप result शायद ही कभी खुद बनाते हैं, क्योंकि एक **[dependency](handlers/dependencies.md)** यह कर देती है: parameter को `Resolve(ask_quantity)` से annotate करें, जहाँ `ask_quantity` आपका लिखा साधारण function है, और SDK उसी mechanism से पूछता है जिसे connection support करता है, legacy session पर live elicitation request या 2026 पर multi-round-trip। एक tool body, दोनों पीढ़ियाँ:

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

वह file पूरी बात एक जगह कह देती है: एक server, एक `Resolve`-backed tool, और एक legacy client तथा एक modern client, दोनों को अपना जवाब मिलता है, in memory। **[Multi-round-trip requests](handlers/multi-round-trip.md)** mechanism समझाता है (`request_state` समेत, जिसे SDK आपके लिए seal और verify करता है); पूछने का हिस्सा **[Elicitation](handlers/elicitation.md)** में है।

!!! warning "यही वह एक जगह है जहाँ port किए गए v1 server का व्यवहार बदलता है"
    आपके अपने tests इससे सबसे पहले टकराते हैं: `Client(mcp)` default रूप से आपके v2 server के सामने 2026-07-28 negotiate करता है,
    इसलिए `ctx.elicit()` call करने वाला tool ऐसे test में fail होता है जो v1 पर pass होता था। सवाल को
    `Resolve(...)` parameter में ले जाएँ (हर पीढ़ी में चलने वाला), या अगर आपको वाकई push व्यवहार चाहिए तो
    test client को `mode="legacy"` पर pin करें।

### Roots, sampling और protocol logging deprecated हैं; `ping` हटा दिया गया {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) तीन पूरी **capabilities** को हर protocol version पर deprecated करता है: roots, sampling और MCP-level logging (`ctx.info()` वगैरह)। यह ऊपर के गायब back-channel से अलग धुरी है; deprecated सिर्फ़ सलाह है, 2025 पीढ़ी के sessions के सामने सब कुछ काम करता रहता है, और wire पर कुछ नहीं बदलता। जो आपको दिखता है वह `MCPDeprecationWarning` है, जो `UserWarning` है, इसलिए default रूप से print होता है; मानकर चलें कि upgrade के बाद आपका पहला `ctx.info(...)` यही कहेगा।

`ping` ज़्यादा सख्त है: deprecated नहीं, protocol से हटा दिया गया। Deprecated features के दो standalone methods भी 2026-07-28 पर इसी तरह हटाए गए हैं, `logging/setLevel` और client का `notifications/roots/list_changed`, और progress notifications अब सिर्फ़ server-to-client हैं।

**[Deprecated features](deprecated.md)** में पूरी table, हर एक का विकल्प, और legacy clients को serve करते समय शांत log चाहिए तो one-line filter है।

### Change notifications एक stream बन जाते हैं {#change-notifications-become-one-stream}

2026-07-28 पर standalone HTTP GET stream और `resources/subscribe` की जगह `subscriptions/listen` लेता है: client एक long-lived stream खोलता है और बताता है कि उसे किस तरह के notifications चाहिए। `MCPServer` इसे बिना कुछ configure किए serve करता है; आप `await ctx.notify_resource_updated(uri)` (और `notify_tools_changed()`, वगैरह) से publish करते हैं, एक middleware हर caller के लिए listen request ठुकरा सकता है, और multi-replica deployments एक साझा `SubscriptionBus` लगाते हैं। Client पर `async with client.listen(...)` stream खोलता है: filter keyword arguments के रूप में जाता है, typed change events वापस आते हैं, और `sub.honored` वह subset है जिसे server deliver करने पर राज़ी हुआ।

Publishing और serving **[Subscriptions](handlers/subscriptions.md)** में है, देखने वाला छोर **[इसके Clients वाले जुड़वाँ page](client/subscriptions.md)** में, और bus **[Deploy & scale](run/deploy.md)** में।

### बाकी, फटाफट {#the-rest-quickly}

* **Identity optional, per-message metadata है।** Request-side `clientInfo` `_meta` key optional है (ज़रूरी जोड़ी `protocolVersion` + `clientCapabilities` है), और `serverInfo` `server/discover` result body से बाहर चला गया: servers इसके बजाय उसे हर 2026 पीढ़ी के result के `_meta` में stamp करते हैं ([spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002))। SDK हमेशा stamp करता है; जब server अपनी पहचान नहीं बताता (उदाहरण के लिए, किसी middleware ने key हटा दी) तो `client.server_info` `None` होता है। **[The low-level Server](advanced/low-level-server.md)** wire पर stamp दिखाता है।
* **Requests bodies parse किए बिना route हो सकती हैं।** Modern HTTP requests `Mcp-Method` ले जाती हैं (और तीन tool जैसी calls के लिए `Mcp-Name`); `x-mcp-header` से annotate की गई tool input-schema property को `Mcp-Param-*` header में mirror किया जाता है और server उसे cross-check करता है ([SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243))। Gateways और rate limiters सिर्फ़ headers पर route कर सकते हैं; नियम **[Migration Guide](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)** में हैं।
* **Results cache hints ले जाते हैं।** List और read results `ttlMs` और `cacheScope` declare करते हैं ([SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)); आप उन्हें `cache_hints=` से हर method के लिए set करते हैं, और `Client` built-in response cache के साथ उनका मान रखता है। जो server कोई hints नहीं भेजता (हर pre-2026 server), उसे जस का तस, uncached traffic दिखता है। **[Caching hints](client/caching.md)**।
* **Extensions first class हैं।** Servers और clients reverse-DNS identifiers के नीचे optional capability bundles declare करते हैं ([SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)); built-in `Apps` extension (MCP Apps) reference है। **[Extensions](advanced/extensions.md)** और **[MCP Apps](advanced/apps.md)**।
* **Error codes standardized हो गए।** गायब resource `-32602` है, `error.data` में URI के साथ, और नए spec-reserved codes `-32020` (header mismatch), `-32021` (ज़रूरी capability गायब) और `-32022` (unsupported protocol version) के रूप में दिखते हैं। **[Troubleshooting](troubleshooting.md)** ठीक उन्हीं messages के हिसाब से व्यवस्थित है।
* **Authorization को गलत पकड़ना अब मुश्किल है।** Client authorization code के साथ लौटे `iss` को validate करता है ([RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207); आपका `callback_handler` अब `AuthorizationCodeResult` लौटाता है), register करते समय `application_type` भेजता है, और credentials को कभी किसी दूसरे authorization server के सामने replay नहीं करता। Enterprise कोने में नया: [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) identity-assertion flow। **[Migration Guide](migration.md)** हर OAuth बदलाव की सूची देता है; pages **[OAuth for clients](client/oauth-clients.md)** और **[Identity assertion](client/identity-assertion.md)** हैं।
* **हर server traceable है।** OpenTelemetry middleware के रूप में default रूप से चालू आता है: हर request को एक server span मिलता है, और जब तक process कोई exporter configure न करे, इसकी कोई लागत नहीं। जब दोनों छोर SDK चलाते हैं, तो client `_meta` में W3C trace context भी propagate करता है, इसलिए traces जुड़ जाते हैं। **[OpenTelemetry](run/opentelemetry.md)**।

## v1 से upgrade कर रहे हैं? {#upgrading-from-v1}

* **[Migration Guide](migration.md)** बदलने वाली हर चीज़ की पूरी, सटीक सूची है; यह page "क्यों" था।
* **v1.x कहीं नहीं जा रहा।** वह maintenance में जाता है, critical fixes और security patches पाता रहता है, और 2026-07-28 spec release की कोई चीज़ उसे नहीं तोड़ती; उसके docs [/v1/](https://py.sdk.modelcontextprotocol.io/v1/) पर हैं। अगर आप `mcp` पर निर्भर कोई library publish करते हैं और migrate करने के लिए तैयार नहीं हैं, तो एक upper bound रखें (उदाहरण के लिए `mcp>=1.28,<2`) ताकि unpinned resolve 1.x पर रहे।
* कुछ खुरदुरा, उलझाने वाला या टूटा हुआ लगा? **[v2 feedback दर्ज करें](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**; सब पढ़ा जाता है।
