---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# 用戶端 {#the-client}

Python 程式要和 MCP 伺服器對話，靠的就是 **`Client`**。

它是一個物件，只有一套生命週期：建立它、進入 `async with`、呼叫方法。每個協定動作（列出工具、呼叫其中一個、讀取資源、算繪提示詞）都是它上面的一個 `async` 方法，回傳有型別的結果。

## 你的第一個用戶端 {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

最上面的伺服器只是讓你有東西可以連而已。用戶端就是標示出來的那五行。

* `Client(mcp)` 拿到的是**伺服器物件本身**。這就是記憶體內傳輸：沒有子處理程序、沒有連接埠、沒有 HTTP。這一頁的每個範例，以及你寫的每個測試，都是這樣連線的。
* `async with` 就是**生命週期**。進入時連線並協商；離開時斷線。沒有 `connect()` / `close()` 這種成對的方法，而且區塊結束後 `Client` 不能再重複使用。
* 在區塊內，連線的各項資訊已經以普通屬性的形式準備好了。

### 可以傳什麼給 `Client` {#what-you-can-pass-to-client}

`Client` 接受一個位置引數，並依它的型別決定傳輸方式：

* `MCPServer`（或低階的 `Server`）實例：在**同一個處理程序內**連線。
* URL 字串（`Client("http://localhost:8000/mcp")`）：Streamable HTTP，也就是正式環境的路徑。
* 一個**傳輸**：任何可以 `async with ... as (read, write)` 的東西，例如包住子處理程序的 `stdio_client(...)`。

這一頁其餘的內容在這三種情況下完全相同。標頭、子處理程序、逾時，以及 `Transport` 協定另外有專屬的頁面：**[用戶端傳輸方式](transports.md)**。

### 連線後的用戶端上有什麼 {#whats-on-a-connected-client}

四個唯讀屬性，一進入區塊就填好了：

* `client.server_info`：伺服器的身分；如果是不回報身分的 2026 世代伺服器，則為 `None`（python-sdk 伺服器預設會回報）。這裡的 `server_info.name` 是 `"Bookshop"`，`server_info.version` 則是伺服器回報的值。
* `client.server_capabilities`：伺服器能做什麼（`tools`、`resources`、`prompts`、`completions`……）。伺服器沒有的能力會是 `None`。
* `client.protocol_version`：雙方談妥的協定版本。這裡是 `"2026-07-28"`。
* `client.instructions`：伺服器的 `instructions=` 字串；如果沒有設定則為 `None`。

你從頭到尾都沒有挑過協定版本。預設情況下 `Client` 會先探測伺服器，遇到較舊的伺服器就退回傳統的交握，所以同一個用戶端可以對應任何世代的伺服器。需要自己掌控時，完整說明請見 **[協定版本](../protocol-versions.md)**。

!!! tip
    `client.session` 是底層的 `ClientSession`，也就是低階的逃生出口。這一頁的任何內容都用不到它。

## 列出工具 {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` 回傳一個 `ListToolsResult`；工具在 `.tools` 裡。每一個都是 MCP 主機（host）會交給模型的完整定義：

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

而 `tool.input_schema` 是伺服器從函式的型別提示推導出來的 JSON Schema：

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

這份 schema 就是 UI 算繪引數表單所需的一切，也是模型產生合法引數所需的一切。

!!! tip
    `title` 是選填的，所以把工具顯示給人看的 UI 得自己挑：有的話就用 `title`，沒有就用 `name`。`from mcp.shared.metadata_utils import get_display_name` 做的正是這件事，適用於工具、資源、資源範本和提示詞。

## 呼叫工具 {#calling-a-tool}

`call_tool(name, arguments)` 會執行工具，並回傳一個 `CallToolResult`。

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

伺服器的 `lookup_book` 回傳一個 Pydantic 的 `Book`。用戶端看到的是：

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

一個回傳值，三樣東西可讀。各自有不同的使用對象。

### `content`：給模型讀的 {#content-what-the-model-reads}

`content` 是一個**內容區塊**的 `list`，而內容區塊是一個聯集：`TextContent`、`ImageContent`、`AudioContent`、`ResourceLink` 或 `EmbeddedResource`。一個工具可以回傳好幾個，而且種類各異。

這就是為什麼 `main` 在碰 `block.text` 之前，先用 `isinstance(block, TextContent)` 縮窄型別。注意 `isinstance` 之外完全沒有出現 `.text`：型別檢查器不會放行，因為 `ImageContent` 有的是 `.data`，不是 `.text`。這個聯集誠實地表達了工具可以送什麼給你；你的程式碼也應該如此。

### `structured_content`：給應用程式讀的 {#structured_content-what-your-application-reads}

`structured_content` 是工具回傳值的 JSON 形式，符合工具宣告的 `output_schema`。不用剖析字串，不用猜。

兩者同時存在時，是刻意把同一件事講兩遍：`content` 給模型，`structured_content` 給程式碼。結構化的那一半從哪裡來、又該怎麼控制，請見 **[結構化輸出](../servers/structured-output.md)** 頁面。

### `is_error`：工具有沒有失敗 {#is_error-whether-the-tool-failed}

會引發例外的工具，在用戶端這邊**不會**引發例外。它會以一個普通的結果回來，帶著 `is_error=True`。

!!! check
    向 `lookup_book` 要 `"Solaris"`（目錄裡沒有的書名），函式會引發 `ValueError`。呼叫仍然正常回傳：

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    例外的訊息落在 `content` 裡，**模型**可以讀到它並再試一次。這是刻意的設計：工具錯誤是對話的一部分，不是當機。在信任 `structured_content` 之前，一定要先看 `is_error`。

!!! warning
    `is_error=True` 涵蓋的不只是你自己的 `raise`。要一個伺服器根本沒有的工具（`call_tool("does_not_exist", {})`），也不會引發任何例外。你會拿回同樣的形狀：`is_error=True`，`content` 裡是 `Unknown tool: does_not_exist`。只有在伺服器回的是 JSON-RPC **錯誤**而不是結果時，`Client` 的方法才會引發 `MCPError`；伺服器什麼時候產生哪一種，請見 **[處理錯誤](../servers/handling-errors.md)**。

## 資源 {#resources}

資源的動作是成組的：兩種列出的方式，一種讀取的方式。

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` 回傳**具體**的資源，也就是 URI 固定的那些。這裡是：`['catalog://genres']`。
* `list_resource_templates()` 回傳**參數化**的那些。這裡是：`['catalog://genres/{genre}']`。它們分成兩個清單，因為範本在填好之前是不能讀的。
* `read_resource(uri)` 接受一個普通的 `str` URI，兩種都適用：傳入 `"catalog://genres/poetry"`，伺服器會把它比對到範本。

`read_resource` 回傳 `contents`，一個由 `TextResourceContents` 或 `BlobResourceContents` 組成的清單。跟工具內容是同樣的概念：用 `isinstance` 縮窄，再讀 `.text`（或 `.blob`）。

用戶端也可以在資源變更時收到通知。在 2025 世代的連線上，這是 `subscribe_resource(uri)` / `unsubscribe_resource(uri)`——一組 `MCPServer` 沒有實作的方法，所以在 2026-07-28 的線路上（那裡已經沒有這些動作了），請求得到的回應是 `-32601`，「Method not found」。2026 的替代方案是 `subscriptions/listen` 串流，這個 `MCPServer` **有**提供——在那裡 `server_capabilities.resources.subscribe` 是 `True`——而用 `client.listen(...)` 來消費它，就是本節的 **[訂閱](subscriptions.md)** 頁面。

## 提示詞 {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` 告訴你伺服器提供什麼，以及每個提示詞需要什麼：

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` 負責算繪它。引數 dict 是 `str -> str`：提示詞引數永遠是字串。結果是 `messages`，一個 `PromptMessage` 的清單，每個都有 `role` 和一個 `content` 區塊：

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

主機會把這些訊息直接交給模型。整個功能就這樣。

## 自動完成 {#completions}

有自動完成處理函式的伺服器，可以在使用者輸入時自動完成提示詞和資源範本的引數。

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` 指出你正在填的是**哪一個**提示詞或範本：`PromptReference` 或 `ResourceTemplateReference`。
* `argument` 是 `{"name": ..., "value": ...}`：引數本身，以及使用者目前為止輸入的內容。

答案在 `result.completion.values` 裡。輸入 `"p"`，伺服器回的是 `['poetry']`。伺服器端的部分，以及處理函式如何利用**其他**已填好的引數來縮小建議範圍，請見 **[自動完成](../servers/completions.md)** 頁面。

## 分頁 {#pagination}

每個 `list_*` 方法都接受 `cursor=` 關鍵字引數，每個結果都帶有 `next_cursor`。當 `next_cursor` 是 `None`，表示全部拿到了。

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

這個迴圈對任何伺服器都正確。`MCPServer` 會一頁回傳全部，所以 `next_cursor` 是 `None`，迴圈只跑一次，這也是為什麼大部分程式碼從來不寫它。真正會分頁的伺服器，以及游標遵守的規則，請見 **[分頁](../advanced/pagination.md)**。

## 在測試中 {#in-tests}

不需要處理程序、不需要連接埠的 `Client(mcp)`，本身就已經是伺服器的測試工具了。

有一個建構子旗標是專為此設計的：`Client(mcp, raise_exceptions=True)`。它只對記憶體內連線有作用，而 **[測試](../get-started/testing.md)** 頁面會解釋它，並圍繞它建立整套模式。

## 重點回顧 {#recap}

* `Client(x)` 對伺服器物件以記憶體內方式連線，對 URL 字串透過 Streamable HTTP 連線，其他情況則透過傳輸連線。
* `async with` 就是整個生命週期。在裡面，`server_capabilities` 和 `protocol_version` 已經填好；伺服器有提供時，`server_info` 和 `instructions` 也是。
* `list_tools()` 給你每個工具的 `name`、`title`、`description` 和 `input_schema`。
* `call_tool()` 回傳給模型的 `content`、給程式碼的 `structured_content`，以及 `is_error`。會引發例外的工具是一個結果，不是例外。
* `content` 是區塊型別的聯集；讀取前先用 `isinstance` 縮窄。
* `list_resources` / `list_resource_templates` / `read_resource`、`list_prompts` / `get_prompt`，以及 `complete` 補齊了其餘的動作。
* 每個 `list_*` 都接受 `cursor=`；一直迴圈到 `next_cursor` 是 `None` 為止。

伺服器可以向**用戶端**要求的東西，以及你如何回應，請見 **[用戶端回呼](callbacks.md)**。
