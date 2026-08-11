---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# 生命週期 {#lifespan}

大多數真實的伺服器在整個生命期間都會持有某些東西：資料庫連線池、HTTP 用戶端、載入好的模型。

你不會想在每次呼叫時都重新建立它，卻會想乾淨地把它關閉。這就是**生命週期**（lifespan）的用途。

## 有型別的生命週期 {#a-typed-lifespan}

生命週期是一個 `@asynccontextmanager`，它接收伺服器並 `yield` **一個物件**。不論 yield 出什麼，只要伺服器還在執行，每個處理函式都能取用它。

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

由下往上讀：

* `app_lifespan` 在 `yield` **之前**連接 `Database`，並在**之後**於 `finally` 區塊中斷開連線。這就是啟動與關閉。
* 它 yield 出一個 `AppContext`，一個普通的 dataclass，裝著你設定好的東西。今天一個欄位，明天十個。
* `MCPServer("Bookshop", lifespan=app_lifespan)` 就是全部的接線。
* 在工具內部，yield 出來的物件就是 `ctx.request_context.lifespan_context`。

生命週期只會執行**一次**。伺服器啟動時（第一個請求之前）進入，伺服器停止時離開。其間的每個請求都共用同一個 `AppContext`。

!!! info
    如果你寫過 FastAPI 的 `lifespan`，這些你早就會了。同樣的裝飾器、同樣的 `yield`、同樣的 `finally`。

### 模型看到什麼 {#what-the-model-sees}

沒有新東西。`ctx` 是一個 **Context** 參數，所以 SDK 會注入它，它永遠不會進到輸入 schema：

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` 是模型唯一能傳入的引數。生命週期是伺服器自己的事。

`@mcp.resource()` 和 `@mcp.prompt()` 函式也可以接收 `ctx` 參數，寫成不帶型別參數的 `Context`，原因下一節會說明。`ctx` 所攜帶的一切，請見 **[Context](context.md)**。

### 它真的有型別 {#it-really-is-typed}

再看一次型別註記：`ctx: Context[AppContext]`。

就是這一個型別參數，讓型別檢查器把 `ctx.request_context.lifespan_context` **當作** `AppContext`。`.db` 會自動完成；`.dbb` 在你執行伺服器之前就是錯誤。

如果改寫成不帶型別參數的 `Context`，`lifespan_context` 的型別就是 `dict[str, Any]`：型別檢查器無從得知你的生命週期 yield 了什麼。執行時物件還在；你失去的是協助。

!!! warning
    `Context[AppContext]` 是**只限工具**的寫法。把它放在 `@mcp.resource()` 或 `@mcp.prompt()` 函式上，對該處理函式的每次呼叫都會失敗。用戶端會收到錯誤，伺服器記錄會顯示原因：

    ```text
    Context is not available outside of a request
    ```

    在資源和提示詞裡，寫不帶型別參數的 `ctx: Context`。生命週期 yield 出來的物件在執行時仍然是 `ctx.request_context.lifespan_context`；放棄的只是型別參數，不是物件。

!!! tip
    生命週期永遠存在。如果不傳入，SDK 的預設會 yield 一個空的 `dict`，所以 `ctx.request_context.lifespan_context` 是 `{}`，永遠不會是 `None`。這個預設也是為什麼不帶型別參數的 `Context` 會把它的型別定為 `dict[str, Any]`。

## 親眼看它發生 {#watch-it-happen}

「啟動會在第一個請求之前執行」這種句子，不該只能憑信心接受。

把伺服器精簡到只剩生命週期：替 `Database` 加一個 `connected` 旗標，在 `connect()` 和 `disconnect()` 裡切換它，再加一個回報它的工具。

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` 放在模組層級只有一個原因：讓你能從伺服器**外部**觀察它。

!!! check
    三個時刻，三個值：

    * 伺服器啟動前，`database.connected` 是 `False`。匯入模組什麼都沒連接。
    * 執行中，呼叫 `database_status`，結果是 `"connected"`。
    * 停止伺服器，`finally` 區塊就會執行：`database.connected` 又變回 `False`。

    工作正好發生在你放它的地方：圍繞著 `yield`，不是在匯入時，也不是每個請求一次。

## 重點回顧 {#recap}

* `lifespan=` 接收一個 `@asynccontextmanager`，它接收伺服器並 `yield` 一個物件。
* `yield` 之前的程式碼是啟動。之後的 `finally` 是關閉。
* 它只執行一次，涵蓋伺服器的整個生命，而不是每個請求一次。
* 不論 `yield` 什麼，在每個工具、資源和提示詞裡都是 `ctx.request_context.lifespan_context`。
* `ctx: Context[AppContext]` 讓工具裡的這種存取完全有型別。資源和提示詞則用不帶型別參數的 `Context`。
* 沒有 `lifespan=` 代表一個空的 `dict`，永遠不會是 `None`。

在呼叫途中停下來、向使用者詢問只有他們才知道的事的處理函式，就是 **[徵詢（elicitation）](elicitation.md)**。
