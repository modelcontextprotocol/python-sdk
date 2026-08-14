---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# समस्याएँ सुलझाना {#troubleshooting}

इस page की हर heading ठीक वही text है जो SDK किसी error में लिखता है; उसके नीचे बताया गया है कि उसका मतलब क्या है और उसे एक ही कदम में कैसे ठीक करें। अपने traceback (या server log) की आखिरी line को browser के find-in-page से यहाँ खोजें, और सिर्फ़ वही entry पढ़ें।

कई entries इसी एक server पर चलती हैं। एक tool और एक templated resource, दोनों ऐसे city के लिए raise करते हैं जिसे वे नहीं जानते:

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

इस page पर quote किए गए errors असली हैं: SDK का अपना test suite इनमें से हर एक को reproduce करता है।

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

यह MCP error नहीं है। यह anyio का शोर है, और असली error paste की **आखिरी line** है।

`Client.__aenter__` एक task group शुरू करता है। task group से बाहर निकलने वाली हर चीज़ को anyio `ExceptionGroup` में लपेट देता है, इसलिए `async with Client(...)` block से निकलने वाला **हर** exception, वह कुछ भी हो, इसी के अंदर आता है:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

इसके साथ दो काम करें:

1. **सबसे नीचे पढ़ें।** `MCPError: No forecast for 'Atlantis'.` ही असली failure है; इस page पर **उसी** का text खोजें।
2. **block के अंदर catch करें।** `ExceptionGroup` तभी दिखता है जब exception `async with` से **बाहर निकलता** है। अंदर ही catch कर लें तो वही failure सादा `MCPError` है, कहीं कोई group नहीं:

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    **connection** के दौरान होने वाला failure (गलत URL, बंद पड़ा server, इस page पर नीचे दिया
    गया `421`) खुद `async with` से ही बाहर निकलता है, इसलिए उसे catch करने के लिए कोई "अंदर" है
    ही नहीं। ऐसे मामलों में group का सबसे निचला हिस्सा पढ़ें।

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` सिर्फ़ object बनाता है। `async with` तक कुछ भी connect नहीं होता, इसलिए हर method मना कर देता है:

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

इसमें enter करें। `__aenter__` ही connection है:

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` ही disconnection है, इसीलिए भूल जाने लायक कोई `client.close()` है ही नहीं। **[Testing](get-started/testing.md)** ठीक इसी pattern पर बना है।

## `Error executing tool <name>: <message>` और `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

आप एक **result** पढ़ रहे हैं, exception नहीं। `call_tool` ने raise नहीं किया, और fail होने वाले tool के लिए वह कभी करेगा भी नहीं।

`forecast` को ऐसे city के लिए call करें जिसे server नहीं जानता, तो उसका raise किया हुआ exception वापस आता है और request **सफल** mark होती है:

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

जो नाम server ने कभी register ही नहीं किया, उसके लिए `Unknown tool: get_forecast` इसी shape में आता है, और गलत argument भी इसी तरह, tool के input schema के आधार पर, आपका function चलने से पहले ही reject हो जाता है।

सुधार आपके client में है: **`result.is_error` जाँचें**। `call_tool` के चारों ओर लगा `try/except` इनमें से कुछ नहीं पकड़ता, क्योंकि पकड़ने को कुछ है ही नहीं। यह जान-बूझकर है, और इस page की सबसे काम की बात यही है जिसे मन में बिठा लें: call **model** ने चुना था, इसलिए message भी model को मिलता है और दोबारा कोशिश करने का मौका भी। पूरी जानकारी **[errors संभालना](servers/handling-errors.md)** में है, उस `MCPError` वाले रास्ते समेत जो सच में raise **करता** है।

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

आपने `@mcp.tool()` की जगह `@mcp.tool` लिख दिया। `tool()` एक decorator **factory** है: parentheses के बिना Python आपका function उसके `name=` parameter को थमा देता है।

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

parentheses जोड़ें। यही चूक होने पर `@mcp.resource(...)` और `@mcp.prompt()` भी यही बात कहते हैं।

!!! note
    यह module **import** होते ही raise हो जाता है, किसी भी client के जुड़ने से पहले। इसलिए जो
    host आपके server को zero tools के साथ connected दिखाने के बजाय **failed to start** (या
    **disconnected**) दिखाता है, वह इसी shape का है: खुद `python server.py` चलाएँ और traceback
    पढ़ें। type checker भी इसे पकड़ लेता है: function कोई valid `name=` नहीं है।

## `Tool already exists: <name>` {#tool-already-exists-name}

दो registrations ने एक ही tool नाम इस्तेमाल किया। **पहला** जीतता है, दूसरा चुपचाप छोड़ दिया जाता है, और **server log** में आने वाली यह warning ही इसका इकलौता संकेत है:

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` एक ही `forecast` बताती है, और वह `forecast_today` है। इनमें से एक का नाम बदलें। `MCPServer(..., warn_on_duplicate_tools=False)` नतीजा बदले बिना सिर्फ़ warning चुप करा देता है, इसलिए इसे चालू ही रहने दें। resources और prompts पर भी यही नियम और यही log line लागू है (`Resource already exists:`, `Prompt already exists:`)।

## मेरा host एक भी tool नहीं दिखाता {#my-host-lists-zero-tools}

इसके लिए कोई error string नहीं है, और ठीक इसीलिए इसे खोजना मुश्किल है। SDK कभी किसी registered tool को `tools/list` से नहीं हटाता, इसलिए अंदर से बाहर की ओर जाँचें:

* **क्या server शुरू भी हुआ?** बिना parentheses वाला `@mcp.tool` import के समय raise करता है, और कुछ hosts में crash हुआ server खाली server जैसा ही दिखता है। खुद `python server.py` चलाएँ।
* **क्या tool उसी `mcp` पर है जिसे host चला रहा है?** किसी दूसरे module में दूसरा `MCPServer(...)` एक अलग, खाली server है। जाँचें कि host का command असल में कौन-सा object import करता है।
* **क्या दो tools का नाम एक ही था?** तो उनमें से एक गायब है। server log में `Tool already exists:` खोजें।
* **क्या host की सूची पुरानी पड़ गई है?** startup के बाद जोड़ा गया tool सिर्फ़ उन्हीं clients तक पहुँचता है जो `notifications/tools/list_changed` संभालते हैं। host को restart करना सीधा-सादा इलाज है।
* **क्या diverted window के बाहर किसी चीज़ ने `stdout` पर लिखा?** serve करते समय SDK भटके हुए **flushed** stdout को stderr की ओर मोड़ देता है (best-effort: जो environment standard streams बदल देता है, उसे जैसा है वैसा ही serve किया जाता है), लेकिन उससे पहले stdout पर flush हुआ output (echo करती wrapper script, unbuffered process में import-time `print()`) या interpreter exit पर खाली होने वाला buffered `print()` protocol stream पर पहुँच जाता है, और एक भी कचरा line से host connection तोड़ सकता है, जिसे कुछ hosts खाली server की तरह दिखाते हैं। इसके बजाय `logging` module से log करें। host-side checklist का बाकी हिस्सा **[असली host से जुड़ें](get-started/real-host.md)** पर है।

"invalid" tool नाम इस सूची में **नहीं** है: नियम से हटकर रखा गया नाम warning log करता है, पर tool फिर भी register और list होता है।

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

server ने HTTP request को सीधे ठुकरा दिया, ऐसी body के साथ जो JSON-RPC नहीं है, इसलिए python `Client` के पास आपको दिखाने के लिए इस stand-in से बेहतर कुछ नहीं है।

सबसे आम कारण, बाकी सबसे कहीं ज़्यादा, अभी-अभी deploy किया गया Streamable HTTP server है। बिना `transport_security=` के `streamable_http_app()` (और `mcp.run("streamable-http")`) का default **DNS-rebinding protection** है: यह सिर्फ़ वही requests स्वीकार करता है जिनका `Host` header localhost हो। आपके laptop पर यह सही default है, और असली hostname के पीछे गलत:

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

इसे deploy करें, किसी client को इस पर point करें, और connection handshake पर ही fail हो जाता है:

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

server ने असल में जो शब्द भेजे, `421` और `Invalid Host header`, वे आप तक कभी नहीं पहुँचते: 421 body में `Content-Type: application/json` नहीं है, इसलिए client उसे parse नहीं कर सकता। वे **server के log** में हैं, और अगली नज़र वहीं डालनी है:

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

सुधार `transport_security=` है। जिस hostname पर आप सच में serve करते हैं, उसे allowlist करें:

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    पूरा बदलाव बस इतना ही है। बिल्कुल वही client अब connect होता है, `2026-07-28` negotiate करता
    है, और `forecast` call करता है।

हर field का मतलब, reverse-proxy वाला मामला, और deploy के समय बदलने वाली बाकी हर चीज़ **[Deploy और scale](run/deploy.md)** में है। और ठीक नीचे दिया गया `421 Misdirected Request` / `Invalid Host header` यही failure है, दूसरी तरफ़ से देखा हुआ।

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

यह वही `Server returned an error response` है, किसी भी ऐसी चीज़ से देखा हुआ जो python `Client` **नहीं** है: curl, browser का network tab, reverse proxy का access log, या कोई दूसरा SDK।

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` इस status के लिए HTTP का अपना reason phrase है; `Invalid Host header` SDK की response body है; और python `Client` इसी घटना को `Server returned an error response` के रूप में दिखाता है। तीनों एक ही इनकार हैं। जाँच **request में आए `Host` header** पर चलती है, उस address पर नहीं जिससे server bind हुआ, इसलिए public hostname आगे भेजने वाला reverse proxy इसे ठीक वैसे ही trip करता है जैसे सीधा client।

सुधार वही `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` है जो `Server returned an error response` के नीचे दिखाया गया है। इसके दो किनारे नाम लेने लायक हैं:

* `allowed_hosts` की entry exact string होती है। `"mcp.example.com"` बिना port वाले `Host` header से match करती है और `"mcp.example.com:*"` किसी भी explicit port से। दोनों को list करें।
* `Invalid Origin header` body वाला `403` इसी का जुड़वाँ check है जो `Origin` header पर चलता है। यह सिर्फ़ browsers के लिए fire होता है (और कोई `Origin` भेजता ही नहीं), और `allowed_origins=` इसकी allowlist है।

पूरी जानकारी **[Deploy और scale](run/deploy.md)** में है, इस बात समेत कि कब check बंद कर देना ही ईमानदार configuration है।

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

आपका MCP app किसी दूसरे ASGI app के अंदर mount है, और उसका **session manager** किसी ने शुरू नहीं किया।

`mcp.streamable_http_app()` एक Starlette app लौटाता है जिसका अपना lifespan manager शुरू करता है, और `uvicorn server:app` वह lifespan आपके लिए चला देता है। लेकिन Starlette **mounted sub-application का lifespan कभी नहीं चलाता**, इसलिए जैसे ही app किसी `Mount` के अंदर जाता है, manager कभी शुरू नहीं होता और पहली ही request फट पड़ती है:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

server शुरू होता है। route resolve होता है। फिर `uvicorn` हर request पर यह print करता है:

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

client को 500 दिखता है। सुधार **host** app पर एक lifespan है जो `mcp.session_manager.run()` में enter करता है:

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

इसके लिए **[मौजूदा app में जोड़ें](run/asgi.md)** वाला page है, एक app में कई servers और FastAPI समेत। उसी class से दो पड़ोसी strings:

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` manager single-use है; एक ही app के lifespan में दो बार enter करने पर यह मिलता है।
* `mcp.session_manager` सिर्फ़ `streamable_http_app()` call होने के **बाद** ही मौजूद होता है, इसलिए पहले routes बनाएँ और manager को सिर्फ़ lifespan के अंदर ही छुएँ।

## `MCPError: Session not found` {#mcperror-session-not-found}

client ने जो `Mcp-Session-Id` भेजा उसे server नहीं पहचानता, लगभग हमेशा इसलिए कि server **restart** हुआ (या आपको किसी दूसरे instance पर route कर दिया गया)। sessions उसी एक process की memory में रहते हैं।

खोजने को कोई server bug नहीं है। HTTP response एक `404` है जिसकी body JSON-RPC **है**, इसलिए ऊपर वाले `421` के उलट, python `Client` इसे आपको ज्यों का त्यों दिखाता है:

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

सुधार है reconnect करना: `async with Client(...)` block से बाहर निकलें और नए में enter करें, जो नया session negotiate करता है। लंबे समय तक चलने वाले client के लिए इसका मतलब है अपने calls के चारों ओर `MCPError` catch करना और इस message पर reconnect करना, न कि मरे हुए session के अंदर retry करते रहना।

अगर यह restart के **बिना** होता है, तो आप sticky sessions के बिना एक से ज़्यादा worker चला रहे हैं: हर worker की अपनी session table होती है, इसलिए गलत worker पर route हुई request यहीं आ गिरती है। वह पूरी कहानी और उसके दो सुधार (sticky routing, या `stateless_http=True`) **[Deploy और scale](run/deploy.md)** और **[legacy clients को serve करना](run/legacy-clients.md)** में हैं।

server operator के लिए इससे मेल खाती log line है `Rejected request with unknown or expired session ID: <id>`। यह `INFO` पर log होती है, इसलिए आम `WARNING` threshold पर नहीं दिखती। deploy के ठीक बाद इसे झुंड में देखना सामान्य है; हर जुड़ा हुआ client reconnect कर रहा है।

## `MCPError: Method not found` {#mcperror-method-not-found}

एक side ने ऐसी JSON-RPC request भेजी जिसके लिए दूसरी side के पास कोई handler नहीं है, और `e.error.data` उस method का नाम बताता है। आम कारण है **पीढ़ी का मेल न खाना**: ऐसा method जो एक protocol revision में है और दूसरे में नहीं, गलत revision वाले peer को भेज दिया गया, जैसे `2025` पीढ़ी की `resources/subscribe` किसी `2026-07-28` connection पर आ पहुँचे, या `mode="legacy"` पर pin किया हुआ client सिर्फ़ `2026` में मौजूद `subscriptions/listen` भेज दे। कौन-सी side क्या बोलती है, इसका नक्शा **[Protocol versions](protocol-versions.md)** है, और दूसरा जायज़ कारण (एक optional capability जिसके लिए आपने कभी handler register नहीं किया) **[Completions](servers/completions.md)** पर है।

एक चीज़ यह error पैदा **नहीं** करती, भले वह ऐसी request है जिसे आधुनिक protocol ने हटा दिया: `2026-07-28` connection पर `ctx.elicit()` call करता tool। server उस request को **भेजने** से ही मना कर देता है, इसलिए आपको इसके बजाय `Cannot send 'elicitation/create': ...` मिलता है, जो इस page पर और नीचे है।

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

आपका server user से कुछ पूछना चाहता है, और इस client ने कभी कहा ही नहीं कि उससे पूछा जा सकता है।

जब जुड़े हुए client ने form elicitation declare नहीं किया हो, तो elicitation resolver शुरू में ही मना कर देता है, और `e.error.data` ठीक-ठीक बताता है कि क्या गायब है:

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

`Client(...)` को `elicitation_callback=` दें। callback register करना **ही** capability declaration है; कोई दूसरा switch नहीं है:

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

बाकी callbacks (`sampling_callback`, `list_roots_callback`) की सूची **[Client callbacks](client/callbacks.md)** में है, और उनमें से हर एक इसी तरह एक declaration है।

!!! info
    `-32021` है `MISSING_REQUIRED_CLIENT_CAPABILITY`, उन तीन error codes में से एक जो 2026-07-28
    spec जोड़ता है। इनमें से कोई भी exception class नहीं है: ये सब `MCPError` बनकर आते हैं, और
    देखने की जगह `e.error.code` है। `mcp.types` ये constants export करता है। बाकी दो हैं
    `-32020` `HEADER_MISMATCH` (कोई HTTP header अपने साथ वाली request body से मेल नहीं खाता)
    और `-32022` `UNSUPPORTED_PROTOCOL_VERSION` (request ने ऐसा version बताया जो यह server नहीं
    बोलता)। नियम मानने वाला SDK client इनमें से कोई भी पैदा नहीं कर सकता, इसलिए अगर कोई दिखे, तो उस
    चीज़ को देखें जो आपके client और server के बीच requests को बदल रही है।

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

वही कमी जो `Client did not declare the form elicitation capability ...` में है, बस उन रास्तों के शब्दों में जो शुरू में जाँच नहीं करते: server को एक elicitation का जवाब चाहिए था, और जुड़े हुए client ने कोई `elicitation_callback` register नहीं किया।

यह legacy connection पर `ctx.elicit()` से दिखता है, और किसी भी connection पर तब, जब लौटाया गया multi-round-trip सवाल (**[Multi-round-trip requests](handlers/multi-round-trip.md)**) ऐसे client तक पहुँचे जिसके पास जवाब देने को कोई callback नहीं। सुधार बिल्कुल वही है: `Client(...)` को `elicitation_callback=` दें। "user से पूछा ही नहीं गया" का कोई ऐसा रूप नहीं है जो आपके tool को `decline` के रूप में मिले; जिस client से पूछा नहीं जा सकता वह fail हुआ call है, इसलिए अपने tools को इसी हिसाब से बनाएँ।

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

आपके handler ने request के बीच में client तक पहुँचने की कोशिश की, ऐसे connection पर जिसके call में server की ओर से request ले जाने वाला कोई channel नहीं है। तीन server configurations हैं जो किसी call को इस हालत में डालते हैं।

**`2026-07-28` connection: कोई भी transport, हमेशा।** आधुनिक protocol में server-initiated requests हैं ही नहीं, इसलिए server कुछ भेजे जाने से पहले ही मना कर देता है। tool के अंदर `ctx.elicit()` इससे टकराने का classic तरीका है (पहले ही in-memory test पर, क्योंकि `Client(server)` बिना कहे `2026-07-28` negotiate करता है), और `elicitation_callback=` देने से कुछ नहीं बदलता, क्योंकि client तक कभी कोई request पहुँचती ही नहीं जिसका वह जवाब दे:

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**`stateless_http=True` server पर legacy connection।** statelessness का मतलब है हर request अपनी अलग दुनिया है: न session, न server-to-client stream, और इसलिए `elicitation/create` (या `sampling/createMessage`, या `roots/list`) भेजने की कोई जगह नहीं, उस पीढ़ी के लिए भी जिसमें ये मौजूद हैं:

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**`json_response=True` server पर legacy connection।** `POST` का जवाब एक JSON body से दिया जाता है, और एक body में सिर्फ़ response आता है, इसलिए request के बीच `ctx.elicit()` को जिस request-scoped stream की ज़रूरत है, वह यहाँ भी मौजूद नहीं है। session, उसका `Mcp-Session-Id`, और उसकी standalone stream, सब अब भी हैं; सिर्फ़ request-scoped channel गायब है।

message उस method का नाम बताता है जिसे वह भेज नहीं सका। server जो class raise करता है वह `NoBackChannelError` है, पर wire पर सिर्फ़ base `MCPError` जाता है, इसलिए आपके traceback की आखिरी line ऊपर वाला वाक्य है, class का नाम नहीं।

`2026-07-28` client के लिए तीनों में सुधार एक ही है: call के बीच में पीछे न पहुँचें। सवाल को एक **resolver** में ले जाएँ (या खुद `InputRequiredResult` लौटाएँ) और वह **response** का हिस्सा बन जाता है, जिसे हर connection ले जा सकता है:

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

वही सवाल, client पर वही `elicitation_callback`। फ़र्क अंदर ही अंदर है: resolver की वजह से server सवाल को push करने के बजाय call से **लौटा** सकता है, इसलिए server से client की ओर कभी कुछ बहता ही नहीं। इससे हर `2026-07-28` client बच जाता है, server तीनों में से किसी भी configuration में हो। **legacy** client सिर्फ़ इस rewrite से नहीं बचता: `2025-11-25` के पास सवाल लौटाने का कोई तरीका नहीं है, इसलिए legacy connection पर resolver अब भी `elicitation/create` को request-scoped channel से भेजता है, और अब भी ऐसा server चाहिए जो वह channel रखता हो — यानी न `stateless_http=True`, न `json_response=True`। resolvers की जानकारी **[Elicitation](handlers/elicitation.md)** में है; wire पर क्या होता है, वह **[Multi-round-trip requests](handlers/multi-round-trip.md)** में।

!!! check
    `ctx.elicit()` वाला tool गलत नहीं है, वह **2026 से पहले** का है। `mode="legacy"` (classic
    `initialize` handshake, spec `2025-11-25` और उससे पहले) से ऐसे server से जुड़ें जो न
    `stateless_http=True` है न `json_response=True`, और यह काम करता है, क्योंकि वहाँ
    server-to-client channel मौजूद है।
    हर version में क्या है, इसका page **[Protocol versions](protocol-versions.md)** है।

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

client ने जो `requestState` token वापस echo किया, server उसे verify नहीं कर सका, इसलिए उसने round ठुकरा दिया।

`requestState` वह opaque resume token है जो **[multi-round-trip](handlers/multi-round-trip.md)** call अपने legs के बीच साथ ले जाता है। `MCPServer` बाहर जाते समय इसे seal करता है और हर echo को verify करता है, और `tools/call`, `prompts/get`, और `resources/read` पर आने वाले **हर** `request_state` को verify करता है, उस handler के लिए भी जो कभी token बनाता ही नहीं। इसलिए जिस token को इस process ने seal नहीं किया, वह जहाँ भी पहुँचे, ठुकरा दिया जाता है:

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

message जान-बूझकर जड़ रखा गया है: wire कभी नहीं बताता कि कौन-सा check fail हुआ। कारण **server log** में जाता है, और उसे पढ़ना ही पूरा diagnosis है:

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

जो कारण आपको असल में दिखेंगे:

* **`unknown key`** वह है जो मायने रखता है। default sealing key process शुरू होने पर generate होती है, इसलिए जो retry किसी **दूसरे worker** पर, load balancer के पीछे किसी दूसरे instance पर, या **restart के बाद** उसी server पर पहुँचे, वह ऐसी key से seal हुआ था जो इस process के पास कभी थी ही नहीं। वह कोई attacker नहीं है; वह default का एक से ज़्यादा process से सामना है।
* **`audience`**: token किसी **अलग server नाम** वाले instance ने seal किया था। नाम ही seal का default audience claim है, इसलिए fleet को keys के साथ-साथ नाम भी साझा करना होगा (या explicit `RequestStateSecurity(audience=...)` set करना होगा)।
* **`expired`**: round ने seal के `ttl` से ज़्यादा समय लिया, जो 600 seconds है और हर round पर लागू है, हर call पर नहीं।
* **`malformed`** / **`codec error`**: token रास्ते में बदल गया, या वह कभी sealed token था ही नहीं।
* **`request binding`**: token किसी अलग tool, अलग arguments, या अलग method के साथ वापस आया।

multi-process सुधार एक argument है (हर instance पर **वही** `keys`) और साथ में एक ऐसी चीज़ जो argument है ही नहीं: वही server **नाम** (या explicit साझा `audience=`)।

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` seal करती है; सूची की हर key verify करती है, और यही zero-downtime rotation को संभव बनाता है। seal क्या बचाता है और rotation का क्रम क्या है, यह **[Multi-round-trip requests](handlers/multi-round-trip.md#protecting-requeststate)** समझाता है, और **[Deploy और scale](run/deploy.md)** पूरे two-worker failure और उसके दो हिस्सों वाले सुधार से होकर गुज़रता है।

!!! tip
    `keys=[...]` कमज़ोर key को तुरंत ठुकरा देता है, असामान्य रूप से मददगार message के साथ:

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    जैसा कहा है वैसा करें।

## अब भी अटके हैं? {#still-stuck}

* अगर SDK का कोई message इस page पर नहीं है, तो वह अपने आप में report करने लायक documentation bug है।
* [issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues) में खोजें; वहाँ दिखने वाली ज़्यादातर error strings पहले से किसी का write-up हैं।
* कुछ नहीं मिला? पूरे traceback के साथ [issue खोलें](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml), या [MCP Contributors Discord के #python-sdk-dev](https://discord.gg/6CSzBmMkjX) में पूछें।

## सारांश {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` कभी असली error नहीं है। **आखिरी line** पढ़ें; `async with Client(...)` block के **अंदर** `MCPError` catch करने से wrapping पूरी तरह टल जाती है।
* `call_tool` fail होने वाले tool के लिए raise नहीं करता। `Error executing tool ...` और `Unknown tool: ...` results हैं: `result.is_error` जाँचें।
* `Client must be used within an async context manager` -> `async with` इस्तेमाल करें। `Use @tool() instead of @tool` -> parentheses जोड़ें।
* server log में `Tool already exists:` ही इकलौता संकेत है कि एक ही नाम के दो tools सिमटकर एक रह गए।
* एक 421, तीन रूप: `Server returned an error response` (python `Client`), `421 Misdirected Request` / `Invalid Host header` (बाकी सब), `Invalid Host header: <host>` (server log)। सुधार: `transport_security=TransportSecuritySettings(allowed_hosts=[...])`।
* `Task group is not initialized` -> mounted app जिसके host lifespan ने कभी `mcp.session_manager.run()` में enter नहीं किया।
* `Session not found` -> server restart हुआ; reconnect करें।
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` को server-to-client channel चाहिए: `2026-07-28` connection में वह कभी नहीं होता, `stateless_http=True` legacy वाला छीन लेता है, और `json_response=True` request-scoped वाला। resolver इस्तेमाल करें (legacy client को ऐसा server भी चाहिए जो channel रखता हो)। इसका पड़ोसी `Method not found` ऐसे method की request है जो दूसरी side के protocol revision में है ही नहीं।
* `Client did not declare the form elicitation capability ...` और `Elicitation not supported` -> client में `elicitation_callback=` गायब है।
* `Invalid or expired requestState` wire पर कभी नहीं बताता कि क्यों। server log बताता है; `unknown key` का मतलब है workers के बीच `RequestStateSecurity(keys=[...])` साझा करें।
