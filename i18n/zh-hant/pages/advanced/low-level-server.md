---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# 低階 Server {#the-low-level-server}

`@mcp.tool()` 是一層包裝。底下還有第二個伺服器類別 `Server`，講的是原始的 MCP：把協定物件交給它，它就原封不動地放上線路。

`MCPServer` 就是建構在它之上。當便利層礙事時，才往下走：

* 需要送出**精確**的 schema（從檔案載入、從資料庫產生），而不是從 Python 簽章推導出來的。
* 需要完全掌控結果：`_meta`、`is_error`、`structured_content` 的每一個鍵。
* 需要處理 MCP 沒有定義的方法。

其他情況，就留在 `MCPServer`。

## 同一個工具，手工打造 {#the-same-tool-by-hand}

這是 **[工具](../servers/tools.md)** 用九行 `@mcp.tool()` 寫出的 `search_books` 工具，拿掉語法糖之後的樣子：

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

改了三件事，而這三件事就是整個低階 API：

* **處理函式是建構子參數。** `on_list_tools=` 和 `on_call_tool=` 傳進 `Server(...)`。這一層沒有裝飾器，而且每個處理函式的形狀都一樣：`async (ctx, params) -> result`。
* **輸入 schema 自己寫。** `Tool.input_schema` 是普通的 JSON Schema `dict`。沒有人會從型別提示推導它，因為根本沒有型別提示可以推導。
* **結果自己組。** `CallToolResult(content=[TextContent(...)])`，手動建立。沒有任何東西會被包裝、轉換，或從回傳註記推斷出來。

`params` 是解析後的請求：`CallToolRequestParams` 提供 `.name` 和 `.arguments`。`ctx` 是 `ServerRequestContext`：`ctx.session` 用來回頭和用戶端溝通，還有 `ctx.lifespan_context`、`ctx.request_id`，以及 `ctx.meta`，也就是請求傳入的 `_meta`。

!!! info
    如果用過 FastAPI，這個關係你早就認識了。`MCPServer` 是裝飾器加型別提示的那一層；`Server` 是底下的 Starlette。兩者不是競爭對手：`MCPServer` 會建立一個 `Server`，並在上面註冊和這些一模一樣的處理函式。

### 試試看 {#try-it}

這個沒有 Inspector 可用：`mcp dev` 和 `mcp run` 只接受 `MCPServer`。記憶體內的 `Client` 則不在乎；它接收低階 `Server` 的方式和接收 `MCPServer` 完全一樣：

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

和 `@mcp.tool()` 版本產生的文字一模一樣。坦白說有兩個差異：

* `result.structured_content` 是 `None`。高階伺服器會幫你把 `-> str` 包成 `{"result": ...}`；在這裡，你沒建的東西，沒有人會替你建。
* `list_tools` 回傳的是**你**打出來的 schema，一字不差。高階版本每個屬性上都有 `"title": "Query"`，根部還有一個 `"title": "search_booksArguments"`：那是 Pydantic 的產物。在這一層，線路上有的東西，都是你放上去的。

## 沒有人替你檢查 {#nothing-is-checked-for-you}

`MCPServer` 會在函式執行之前就拒絕錯誤的引數，依照它產生的 schema 驗證這次呼叫（**[工具](../servers/tools.md)**）。

`Server` 不做這件事。你的 `input_schema` 是**公告**給用戶端看的；從來不會**套用**到 `params.arguments` 上。

!!! check
    呼叫 `search_books` 時不帶 `limit`，`args["limit"]` 就會引發 `KeyError`。用戶端看到的是：

    ```text
    MCPError: Internal server error
    ```

    一個 JSON-RPC 錯誤，錯誤碼 `-32603`，訊息刻意寫得很籠統：SDK 不會把你的 traceback 洩漏給遠端呼叫端。模型永遠不知道自己哪裡做錯，所以無法重試。（在測試中，`raise_exceptions=True` 會改為浮現真正的例外；請見 **[測試](../get-started/testing.md)**。）

這可以推而廣之。從低階處理函式引發的例外**永遠**是協定錯誤，絕不會是 `is_error=True` 的工具結果。如果希望模型讀到失敗並恢復，就自己驗證 `params.arguments`，然後回傳 `CallToolResult(content=[TextContent(...)], is_error=True)`。這兩種失敗正是 **[處理錯誤](../servers/handling-errors.md)** 的主題。

## 兩個工具，一個處理函式 {#two-tools-one-handler}

`on_call_tool` 是伺服器上所有工具唯一的進入點。依 `params.name` 分派：

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` 公告兩者。`call_tool` 依名稱分派。
* `else` 分支很重要：就算是你從沒列出過的名稱，`Server` 也會照樣把它的 `tools/call` 直接轉進你的處理函式。在那裡引發例外，這次呼叫就會變成和上面一樣的 `-32603`。

## 結構化輸出，手工打造 {#structured-output-by-hand}

在 `Tool` 上宣告 `output_schema`，並在結果上放 `structured_content`。兩者都由你負責：

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

呼叫它，結果會同時帶著兩種表示法：

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

`_meta` 區塊是伺服器的身分戳記：SDK 會把它加到每個 2026 世代的結果上，`version` 取自建構子（沒設定的伺服器會回報空字串）。不能表明身分的伺服器可以用中介軟體把這個鍵拿掉，中介軟體擁有它回傳的結果。

伺服器從不比對這兩個欄位。這個 SDK 的 `Client` 會：回傳的 `structured_content` 如果不符合你宣告的 `output_schema`，`call_tool` 就會引發 `RuntimeError`，訊息以 `Invalid structured content returned by tool search_books` 開頭，接著引用 `jsonschema` 的失敗內容。承諾一個 schema 很便宜；守住承諾是你的事。回傳型別與 schema 的完整階梯請見 **[結構化輸出](../servers/structured-output.md)**。

## `_meta`：給應用程式，不是給模型 {#\_meta-for-the-application-not-the-model}

`content` 是答案中模型會讀的部分。`structured_content` 是同一個答案的型別化資料。`_meta` 是第三個管道：跟著結果一起送給**用戶端應用程式**的資料，完全不屬於答案的一部分。

用它放紀錄 ID、追蹤 ID，任何 UI 需要而提示詞不需要的東西：

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* 建構時寫成 `_meta=`，也就是線路上的名稱。用戶端讀回來時是 `result.meta`。
* 替鍵加上命名空間（`bookshop/record_ids`）。`io.modelcontextprotocol/*` 這些鍵由協定保留。

!!! warning
    `_meta` 是你和用戶端應用程式之間的約定，不保證什麼會送到模型。要呈現什麼由 MCP 主機（host）決定。永遠不要在工具結果的任何部分放機密。

## 能力跟著處理函式走 {#capabilities-follow-your-handlers}

`Server` 公告的方法族群，恰好就是你給了處理函式的那些。上面的 `Bookshop` 只傳了 `on_list_tools` 和 `on_call_tool`，其他什麼都沒有，所以連上它的用戶端會看到：

```json
{"tools": {"listChanged": false}}
```

沒有 `resources`，沒有 `prompts`：背後沒有東西支撐它們。傳入 `on_list_prompts`，`prompts` 就會出現；傳入 `on_completion`，`completions` 就會出現。

`MCPServer` 不管你有沒有註冊，都一律公告工具、資源和提示詞，因為它的管理器永遠存在。在這一層，宣告**就是**那個建構子呼叫。

## 生命週期泛型 {#the-lifespan-generic}

`Server` 對其生命週期 yield 出的型別是泛型的。註記一次，這個物件在每個出現的地方都有型別：

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* 生命週期是一個 `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`；在 `async` 產生器上套 `@asynccontextmanager` 就正好得到這個。
* 它 `yield` 出的東西會變成 `ctx.lifespan_context`，而因為處理函式註記為 `ServerRequestContext[Catalog]`，`.search(...)` 可以自動完成，也能通過型別檢查。
* 伺服器啟動時進入一次，停止時離開一次。啟動、收尾，以及 `MCPServer` 對同一個概念的版本，請見 **[生命週期](../handlers/lifespan.md)**。

沒有 `lifespan=` 的話，`ctx.lifespan_context` 是一個空的 `dict`。

## 自己的方法 {#a-method-of-your-own}

建構子涵蓋 MCP 定義的方法。其他的一切由 `add_request_handler` 負責：

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* 第一個引數是方法字串。通知有個孿生的 `add_notification_handler`。
* `params_type` 是傳入的 `params` 在處理函式執行**之前**用來驗證的模型，所以自訂方法**確實**享有工具沒有的驗證。繼承 `RequestParams`，讓 `_meta` 欄位和其他方法一樣解析。
* 處理函式回傳 `BaseModel`、`dict` 或 `None`。SDK 會把它序列化成 JSON-RPC 結果。

一個坦白的提醒：高階 `Client` 只有對應 MCP 定義方法的動詞，所以沒有 `client.reindex()`。廠商方法是給已經知道它存在的對端用的：你同時發佈的用戶端，或是你自己另一個講 JSON-RPC 的服務。

有一個方法你不能占用：

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

交握屬於執行器。`server/discover`、`ping`，以及其他所有內建方法，都可以替換。

!!! tip
    那則錯誤裡提到的 `Server.middleware` 會包住**每一則**傳入訊息，包括 `initialize`。如果想做的是觀察或改寫流量，而不是回應新方法，請從 **[中介軟體](middleware.md)** 開始。

## 其他處理函式 {#the-other-handlers}

下面每一項都是一個你現在已經有詞彙可以理解的概念；每一項都有自己的頁面。

* `on_call_tool`、`on_get_prompt` 和 `on_read_resource` 可以回傳 `InputRequiredResult` 取代正常結果，暫停呼叫並向用戶端要求輸入；請見 **[多輪往返（multi-round-trip）請求](../handlers/multi-round-trip.md)**。忠於這一層的風格，沒有任何東西會替你裝好：`MCPServer` 預設會封裝 `requestState`，在這裡你設定的 `request_state` 會一字不差地跨過線路，直到你用 `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` 選擇加入：一行（兩個名稱都從 `mcp.server.request_state` 匯入）就能得到和 `MCPServer` 完全相同的封裝與驗證（**[保護 `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**）。
* `on_list_resources`、`on_read_resource`、`on_list_prompts`、`on_get_prompt`、`on_completion` 是其他基本元件的同一個 `(ctx, params) -> result` 形狀。
* `on_subscriptions_listen` 負責 2026-07-28 的 `subscriptions/listen` 串流。傳入一個建構在 `SubscriptionBus` 之上的 `ListenHandler`，並從其他處理函式把事件發佈到 bus；完整的組合方式請見 **[訂閱](../handlers/subscriptions.md)**。
* `server.streamable_http_app()` 回傳的 Starlette 應用程式和 `MCPServer` 的一樣；照 **[執行伺服器](../run/index.md)** 部署其他 ASGI 應用程式的方式部署它。這一層沒有 `server.run(transport=...)`：`server.run(read_stream, write_stream, server.create_initialization_options())` 透過一對串流驅動一條連線，而這一行就是全部。

## 重點回顧 {#recap}

* 低階 `Server` 以 `on_*` **建構子參數**接收處理函式；每個處理函式都是 `async (ctx, params) -> result`。
* `input_schema` dict 自己寫，`CallToolResult` 自己組。沒有任何東西會替你推導、包裝或驗證。
* 處理函式裡的例外是 `-32603` 協定錯誤。模型讀得到的工具錯誤，是**你**回傳的 `is_error=True` 的 `CallToolResult`。
* 結果上的 `_meta` 是給用戶端應用程式的，不是給模型的。
* `Server[T]` 對其生命週期 yield 出的東西是泛型的；`ctx.lifespan_context` 是有型別的 `T`。
* `add_request_handler(method, params_type, handler)` 可以服務任何方法。`initialize` 被保留。
* `Server` 公告的能力，由你註冊了哪些處理函式推導而來。

`Client(server)` 對兩種伺服器一視同仁，因為它們**就是**同一個協定，這正是重點所在。再往下一層根本不是類別：是 **[中介軟體](middleware.md)**。
