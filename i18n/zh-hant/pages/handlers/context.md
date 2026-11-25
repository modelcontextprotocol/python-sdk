---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Context {#the-context}

工具的引數來自模型。其他的一切（正在處理的請求、所在的伺服器、與用戶端溝通的方式）都來自同一個物件：**`Context`**。

不需要自己建立，也不需要設定，只要開口要就好。

## 開口要它 {#ask-for-it}

在任何工具上加一個以 `Context` 註記的參數：

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* SDK 會為每個請求建立一個全新的 `Context` 並傳進來。
* 參數的**名稱不重要**。`ctx`、`context`、`c` 都可以：SDK 是靠型別註記找到它的。
* 資源和提示詞也可以用同樣的方式宣告一個。
* `ctx.request_id` 是函式此刻正在處理的那個請求的 id。

!!! info
    如果用過 FastAPI，這一招應該不陌生：用框架自己的型別宣告一個參數（那邊是 `Request`，這邊是 `Context`），框架就會幫你補上。不用註冊，不用設定：型別註記就是整套機制。

### 模型看不到它 {#invisible-to-the-model}

這是要記在心裡的部分。以下是 `tools/list` 針對 `search_books` 回報的輸入 schema：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

只有一個屬性。`ctx` 不是引數：它永遠不會出現在 schema 裡，模型永遠不會知道它的存在，也沒有任何用戶端能填入它。這是你和 SDK 之間的約定，在線路上看不到。

### 試試看 {#try-it}

用 MCP Inspector 執行伺服器：

```console
uv run mcp dev server.py
```

`search_books` 的表單只有一個 `query` 欄位。用 `dune` 呼叫它：

```text
[request 3] Found 3 books matching 'dune'.
```

數字是這次剛好輪到的請求編號。再呼叫一次工具，數字就會變：每個請求都有自己的 `Context`。

## 它給你什麼 {#what-it-gives-you}

注入的物件很小。除了 `request_id` 之外：

* `await ctx.read_resource(uri)`：在工具內部讀取伺服器**自己的**資源。下一節會介紹。
* `await ctx.report_progress(progress, total, message)`：在長時間的呼叫期間，把進度串流回傳給呼叫端。完整說明請見 **[進度](progress.md)**。
* `await ctx.elicit(message, schema)` 和 `await ctx.elicit_url(...)`：暫停工具，向使用者問一個問題。那是 **[徵詢（elicitation）](elicitation.md)**。
* `ctx.session`：伺服器這一側與這個用戶端的對話。要送給用戶端的通知都在這裡；最後一節會用到它。
* `ctx.headers`：傳輸方式帶過來的請求標頭，在 stdio 上則是 `None`。用 `(ctx.headers or {}).get("x-...")` 讀取自訂標頭。標頭是用戶端提供的輸入，拿來傳語系或功能旗標沒問題，但絕不能當作身分。
* `ctx.request_context`：原始的每請求紀錄。最常用到的欄位是 `lifespan_context`，也就是啟動程式碼 yield 出來的物件（見 **[生命週期](lifespan.md)**）。

記錄刻意不在這張清單上。伺服器和其他 Python 程式一樣，用 Python 的 `logging` 模組記錄。**[記錄](logging.md)** 這一頁簡短說明了原因。

!!! tip
    注入只發生在你註冊的那個函式上。工具呼叫的輔助函式不會拿到自己的 `Context`；把 `ctx` 當作普通引數往下傳就好。沒有什麼環境中的「目前 context」可以從別處取得。

## 讀取自己的資源 {#read-your-own-resources}

伺服器的資源不只是給用戶端用的。工具也可以讀取：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` 透過和 `resources/read` 同一套登錄機制解析 URI，所以工具拿到的東西和用戶端拿到的一樣：一個 `ReadResourceContents` 的可迭代物件，每個內容區塊一個。這個 URI 只有一個：

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` 正是 `genres()` 回傳的內容。單一事實來源：用戶端瀏覽這個資源，工具取用它，沒有人需要複製那個字串。
* `describe_catalog` 唯一的參數是 `Context`，所以它的輸入 schema **完全沒有屬性**。模型用 `{}` 呼叫它。

## 告訴用戶端清單變了 {#tell-the-client-the-list-changed}

伺服器提供的內容並不是在 import 時就固定下來的。可以在執行時註冊工具，然後告訴用戶端：

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` 把一個普通函式註冊成工具：名稱、描述和 schema 的推導方式與 `@mcp.tool()` 完全相同。
* `await ctx.session.send_tool_list_changed()` 會送出 `notifications/tools/list_changed`。收到它的用戶端會再次呼叫 `tools/list`，然後看到 `recommend_book`。

同系列的還有 `send_resource_list_changed()`、`send_prompt_list_changed()`，以及針對某個特定資源變更的 `send_resource_updated(uri)`。

在 2026-07-28 連線上，用戶端只會在自己開啟的 `subscriptions/listen` 串流上收到變更通知，所以上面的 `send_*` 方法到不了那些串流。`Context` 的發布方法會一次送達所有已訂閱的串流：`await ctx.notify_tools_changed()`、`await ctx.notify_prompts_changed()`、`await ctx.notify_resources_changed()` 和 `await ctx.notify_resource_updated(uri)`。完整說明（包括跨副本橫向擴展）請見 **[訂閱](subscriptions.md)**。

!!! check
    在有人執行 `enable_recommendations` 之前，你承諾的那個工具並不存在。硬是呼叫它，結果會是模型讀得懂的錯誤：

    ```text
    Unknown tool: recommend_book
    ```

    執行 `enable_recommendations` 之後，一模一樣的呼叫就成功了。工具清單是真正動態的：`tools/list` 反映的是**此刻**註冊了什麼。

## 重點回顧 {#recap}

* 用 `Context` 註記一個參數（在工具、資源或提示詞裡），SDK 就會注入它。名稱隨你取。
* 模型看不到它：輸入 schema 永遠只包含真正的引數。
* `ctx.request_id` 標識請求；`ctx.request_context.lifespan_context` 是啟動時 yield 出來的東西。
* `await ctx.read_resource(uri)` 讓工具讀取伺服器自己的資源。
* `ctx.session` 是回到用戶端的通道：`send_tool_list_changed()` 和同系列的方法會通知它重新抓取你改過的清單。
* 進度回報和徵詢也都從 `Context` 開始；各有自己的頁面。

模型永遠看不到、由你自己的函式填入的參數，就是 **[相依性](dependencies.md)**。
