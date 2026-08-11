---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# Client {#the-client}

**`Client`** वह ज़रिया है जिससे Python program किसी MCP server से बात करता है।

यह एक object है जिसका एक ही lifecycle है: इसे बनाएँ, `async with` में enter करें, methods call करें। protocol का हर verb (tools की सूची लेना, किसी tool को call करना, resource पढ़ना, prompt render करना) इस पर एक `async` method है जो typed result लौटाता है।

## आपका पहला client {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

ऊपर वाला server सिर्फ़ इसलिए है ताकि connect करने के लिए कुछ हो। client वे पाँच highlighted lines हैं।

* `Client(mcp)` को **server object ही** दिया गया है। यही in-memory transport है: न subprocess, न port, न HTTP। इस page का हर उदाहरण, और आपका लिखा हर test, इसी तरह connect करता है।
* `async with` ही **lifecycle** है। इसमें enter करते ही connect और negotiate होता है; बाहर निकलते ही disconnect। कोई `connect()` / `close()` जोड़ी नहीं है, और block खत्म होने के बाद `Client` दोबारा इस्तेमाल नहीं हो सकता।
* block के अंदर connection की जानकारी पहले से सादी properties के रूप में मौजूद है।

### `Client` को क्या दे सकते हैं {#what-you-can-pass-to-client}

`Client` एक positional argument लेता है और उसके type से transport तय करता है:

* `MCPServer` (या low-level `Server`) instance: **in-process** connect होता है।
* URL string (`Client("http://localhost:8000/mcp")`): Streamable HTTP, production वाला रास्ता।
* **transport**: कोई भी चीज़ जिसे आप `async with ... as (read, write)` कर सकें, जैसे subprocess को wrap करने वाला `stdio_client(...)`।

इस page की बाकी हर चीज़ तीनों में एक जैसी है। Headers, subprocesses, timeouts और `Transport` protocol का अपना अलग page है: **[Client transports](transports.md)**।

### connected client पर क्या है {#whats-on-a-connected-client}

चार read-only properties, जो block में enter करते ही भर जाती हैं:

* `client.server_info`: server की पहचान, या `None` अगर 2026 पीढ़ी का server इसे report नहीं करता (python-sdk servers default रूप से करते हैं)। यहाँ `server_info.name` `"Bookshop"` है, और `server_info.version` वही है जो server report करता है।
* `client.server_capabilities`: server क्या कर सकता है (`tools`, `resources`, `prompts`, `completions`, ...)। जो capability server के पास नहीं है वह `None` होती है।
* `client.protocol_version`: वह protocol version जिस पर दोनों पक्ष सहमत हुए। यहाँ यह `"2026-07-28"` है।
* `client.instructions`: server की `instructions=` string, या `None` अगर उसने कोई set नहीं की।

आपने कोई protocol version नहीं चुना। default रूप से `Client` server को probe करता है और पुराने servers पर पुराने classic handshake पर लौट आता है, इसलिए एक ही client किसी भी पीढ़ी के server के साथ काम करता है। जब इसे नियंत्रित करने की ज़रूरत हो, पूरी जानकारी **[Protocol versions](../protocol-versions.md)** में है।

!!! tip
    `client.session` अंदर का `ClientSession` है, low-level escape hatch।
    इस page की किसी भी चीज़ के लिए आपको इसकी ज़रूरत नहीं पड़ेगी।

## tools की सूची लेना {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` एक `ListToolsResult` लौटाता है; tools `.tools` में हैं। हर एक वह पूरी definition है जो host किसी model को देगा:

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

और `tool.input_schema` वह JSON Schema है जो server ने function के type hints से निकाला:

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

UI को argument form दिखाने के लिए, और model को valid arguments बनाने के लिए, जो कुछ चाहिए वह सब इसी schema में है।

!!! tip
    `title` optional है, इसलिए किसी इंसान को tools दिखाने वाले UI को चुनना पड़ता है: `title` हो तो वही,
    नहीं तो `name`। `from mcp.shared.metadata_utils import get_display_name` ठीक यही करता है,
    tools, resources, resource templates और prompts के लिए।

## tool call करना {#calling-a-tool}

`call_tool(name, arguments)` tool चलाता है और आपको `CallToolResult` वापस देता है।

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

server का `lookup_book` एक Pydantic `Book` लौटाता है। client को यह दिखता है:

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

एक return value, पढ़ने की तीन चीज़ें। हर एक को पढ़ने वाला अलग है।

### `content`: जो model पढ़ता है {#content-what-the-model-reads}

`content` **content blocks** की एक `list` है, और content block एक union है: `TextContent`, `ImageContent`, `AudioContent`, `ResourceLink`, या `EmbeddedResource`। एक tool कई blocks लौटा सकता है, अलग-अलग तरह के।

इसीलिए `main` `block.text` को छूने से पहले `isinstance(block, TextContent)` से narrow करता है। ध्यान दें कि `isinstance` के बाहर कहीं `.text` नहीं है: type checker इसकी अनुमति नहीं देगा, क्योंकि `ImageContent` में `.data` है, `.text` नहीं। tool आपको क्या भेज सकता है, इस बारे में union ईमानदार है; आपका code भी होना चाहिए।

### `structured_content`: जो आपका application पढ़ता है {#structured_content-what-your-application-reads}

`structured_content` tool की return value JSON के रूप में है, जो tool के declared `output_schema` से मेल खाती है। न string parsing, न अंदाज़ा।

जब दोनों मौजूद हों तो वे जानबूझकर एक ही बात दो बार कहते हैं: `content` model के लिए है, `structured_content` code के लिए। structured वाला हिस्सा कहाँ से आता है, और उसे कैसे नियंत्रित करें, यह **[Structured output](../servers/structured-output.md)** page पर है।

### `is_error`: tool fail हुआ या नहीं {#is_error-whether-the-tool-failed}

जो tool raise करता है वह आपके client में raise **नहीं** होता। वह `is_error=True` के साथ एक साधारण result के रूप में लौटता है।

!!! check
    `lookup_book` से `"Solaris"` माँगें (ऐसा title जो catalog में नहीं है) और function
    `ValueError` raise करता है। call फिर भी सामान्य रूप से लौटता है:

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    exception का message `content` में पहुँचा, जहाँ **model** उसे पढ़कर दोबारा कोशिश कर सकता है। यह
    जानबूझकर है: tool error बातचीत का हिस्सा है, crash नहीं। `structured_content` पर भरोसा करने से
    पहले हमेशा `is_error` देखें।

!!! warning
    `is_error=True` सिर्फ़ आपके अपने `raise` तक सीमित नहीं है। ऐसा tool माँगें जो server के पास है ही नहीं
    (`call_tool("does_not_exist", {})`) और कुछ raise नहीं होता। आपको वही shape वापस मिलता है,
    `is_error=True` और `content` में `Unknown tool: does_not_exist`। `Client` का कोई method
    `MCPError` तभी raise करता है जब server result की जगह JSON-RPC **error** से जवाब दे, और
    server कब क्या भेजता है यह **[errors संभालना](../servers/handling-errors.md)** में बताया गया है।

## Resources {#resources}

resource verbs जोड़ियों में आते हैं: सूची लेने के दो तरीके, पढ़ने का एक।

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` **concrete** resources लौटाता है, जिनका URI तय है। यहाँ: `['catalog://genres']`।
* `list_resource_templates()` **parameterised** वाले लौटाता है। यहाँ: `['catalog://genres/{genre}']`। ये दो अलग सूचियाँ हैं क्योंकि template तब तक पढ़ा नहीं जा सकता जब तक आप उसे भर न दें।
* `read_resource(uri)` एक सादा `str` URI लेता है और दोनों पर काम करता है: `"catalog://genres/poetry"` दें और server उसे template से match कर लेता है।

`read_resource` `contents` लौटाता है, `TextResourceContents` या `BlobResourceContents` की सूची। वही तरीका जो tool content का है: `isinstance` से narrow करें, फिर `.text` (या `.blob`) पढ़ें।

client को यह भी बताया जा सकता है कि कोई resource कब बदला। 2025 पीढ़ी के connections पर यह `subscribe_resource(uri)` / `unsubscribe_resource(uri)` है - methods की ऐसी जोड़ी जिसे `MCPServer` implement नहीं करता, इसलिए 2026-07-28 wire पर (जहाँ ये verbs अब मौजूद नहीं हैं) request का जवाब `-32601`, *Method not found* आता है। 2026 में इसकी जगह `subscriptions/listen` stream है, जिसे `MCPServer` serve **करता है** - वहाँ `server_capabilities.resources.subscribe` `True` है - और उसे `client.listen(...)` से consume करना इस section का **[Subscriptions](subscriptions.md)** page है।

## Prompts {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` बताता है कि server क्या देता है और हर prompt को क्या चाहिए:

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` उसे render करता है। arguments dict `str -> str` है: prompt arguments हमेशा strings होते हैं। result `messages` है, `PromptMessage` की सूची, जिनमें हर एक का `role` और एक `content` block है:

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

host ये messages सीधे model को दे देता है। पूरा feature बस इतना ही है।

## Completions {#completions}

जिस server में completion handler हो वह user के type करते-करते prompt और resource-template arguments autocomplete कर सकता है।

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` बताता है कि आप **कौन-सा** prompt या template भर रहे हैं: `PromptReference` या `ResourceTemplateReference`।
* `argument` `{"name": ..., "value": ...}` है: argument और user ने अब तक जो type किया है।

जवाब `result.completion.values` में है। `"p"` type करें और server `['poetry']` लौटाता है। server वाला पक्ष, और handler पहले से भरे **बाकी** arguments का इस्तेमाल अपने सुझाव कम करने के लिए कैसे करता है, यह **[Completions](../servers/completions.md)** page पर है।

## Pagination {#pagination}

हर `list_*` method एक `cursor=` keyword लेता है और हर result में `next_cursor` होता है। जब `next_cursor` `None` हो, आपके पास सब कुछ है।

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

यह loop हर server के साथ सही है। `MCPServer` सब कुछ एक ही page में लौटाता है, इसलिए `next_cursor` `None` होता है और loop एक बार चलता है, यही वजह है कि ज़्यादातर code इसे कभी लिखता ही नहीं। जो servers सच में page करते हैं, और cursors जिन नियमों का पालन करते हैं, वे **[Pagination](../advanced/pagination.md)** में हैं।

## tests में {#in-tests}

बिना process और बिना port वाला `Client(mcp)` अपने आप में server के लिए test harness है।

इसी के लिए एक constructor flag बना है: `Client(mcp, raise_exceptions=True)`। इसका असर सिर्फ़ in-memory connections पर होता है, और **[Testing](../get-started/testing.md)** वह page है जो इसे समझाता है और इसके चारों ओर पूरा pattern बनाता है।

## सारांश {#recap}

* `Client(x)` server object से in-memory connect होता है, URL string से Streamable HTTP पर, और बाकी किसी भी चीज़ से transport के ज़रिए।
* `async with` ही पूरा lifecycle है। इसके अंदर `server_capabilities` और `protocol_version` पहले से भरे होते हैं; server दे तो `server_info` और `instructions` भी।
* `list_tools()` आपको हर tool का `name`, `title`, `description` और `input_schema` देता है।
* `call_tool()` model के लिए `content`, आपके code के लिए `structured_content`, और `is_error` लौटाता है। raise करने वाला tool एक result है, exception नहीं।
* `content` block types का union है; पढ़ने से पहले `isinstance` से narrow करें।
* `list_resources` / `list_resource_templates` / `read_resource`, `list_prompts` / `get_prompt`, और `complete` बाकी verbs पूरे करते हैं।
* हर `list_*` `cursor=` लेता है; `next_cursor` के `None` होने तक loop करें।

server *client* से जो चीज़ें माँग सकता है, और आप उनका जवाब कैसे देते हैं, वह **[Client callbacks](callbacks.md)** है।
