---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# 中介軟體 {#middleware}

**中介軟體（middleware）**是一個非同步函式，包住伺服器收到的每一則訊息。

寫成 `async (ctx, call_next)` 的形式，再附加到 `server.middleware` 就好。整個 API 就這樣。

!!! warning
    中介軟體清單在原始碼裡標示為**暫定（provisional）**：它的簽章和語意可能在 2.x 的小版本中變動。用它來**觀察**（計時、記錄、追蹤）和**拒絕**訊息；不要把它當成伺服器賴以運作的基礎。

`MCPServer` 在建構時接收這份清單（`MCPServer(name, middleware=[...])`），並以 `mcp.middleware` 公開；低階的 `Server` 則以 `server.middleware` 公開同一份清單。下面的範例使用低階的 `Server`；如果還沒見過 `Server(name, on_call_tool=...)`，請先讀 **[低階 Server](low-level-server.md)**。

## 一個計時中介軟體 {#a-timing-middleware}

一個伺服器、一個工具、一個中介軟體，記錄每則訊息花了多久：

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` 就是處理函式收到的同一個 `ServerRequestContext`。`ctx.method` 是原始的方法字串；`ctx.params` 是原始的參數，尚未經過**任何**驗證。
* `call_next(ctx)` 會執行鏈上剩下的部分：驗證、查找處理函式、你的處理函式。把它的回傳值原樣回傳，回應就不會被動到。
* `try`/`finally` 是刻意的：引發例外的處理函式一樣會被計時，因為失敗會以 `call_next` 拋出的例外形式抵達你的中介軟體。
* `server.middleware.append(...)` 完成註冊。清單由最外層開始執行，所以 `middleware[0]` 是最靠近線路的那一個。

### 試試看 {#try-it}

連上一個用戶端，列出工具，呼叫其中一個。記錄裡會有**三**行：

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

呼叫了兩次，卻得到三行。第一行是 `server/discover`：這是用戶端為了建立連線而送出的請求，早在你要求任何東西之前。

重點就在這裡。中介軟體包住**每一則**傳入的訊息：

* 連線建立階段：`server/discover`，或在舊版工作階段（session）上的 `initialize` 和 `notifications/initialized`。
* 每一個請求和每一則通知。對通知而言，`ctx.request_id is None`，`call_next(ctx)` 回傳 `None`，而你回傳的任何東西都會被丟棄。
* 連伺服器沒有處理函式的方法也一樣：`call_next` 會引發 `MCPError(-32601, "Method not found")`，**穿過**你的中介軟體一路送到用戶端。

## 在裡面能做什麼 {#what-you-can-do-inside-one}

依照該有的猶豫程度，由低到高排列：

* **觀察。**計時、計數、記錄。就是上面的範例。
* **拒絕。**不呼叫 `call_next(ctx)`，**改為**引發 `MCPError`，那一則訊息就會以 JSON-RPC 錯誤回應。連線不會斷；下一則訊息照常通過。伺服器就是這樣依呼叫端控管 `subscriptions/listen` 的：訂閱頁面的 **[決定誰可以觀看](../handlers/subscriptions.md#deciding-who-may-watch)** 有逐步說明。
* **改寫。**`ctx` 是一個 dataclass：`await call_next(dataclasses.replace(ctx, params=...))` 會把和用戶端送來的不同的參數交給鏈上剩下的部分。絕對不要對 `initialize` 這麼做：用戶端拿到的結果是根據你改寫後的參數建立的，但伺服器提交連線狀態時用的是線路上原本的參數。雙方可能在交握結束時，對彼此協商出的內容認知不一致。
* **回答。**不呼叫 `call_next(ctx)` 就直接回傳一個結果，它會作為你的回應送到用戶端。`call_next` 交給你的是完成的線路格式，而管線絕不會修補你回傳的東西，所以整個封包都由你負責：在 2026 世代的連線上，這包括 `serverInfo` 的 `_meta` 戳記，SDK 會替處理函式的結果加上它，但不會替你的加。

!!! check
    `initialize` 是中介軟體包住的東西之一，而且這是它**唯一**的掛鉤點。試著用 `add_request_handler` 接管它，SDK 會拒絕：

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` 是就地處理的：在你的中介軟體鏈回傳之前，伺服器不會再讀取任何傳入的訊息。因此在處理 `initialize` 時等待一個伺服器對用戶端的請求（`ctx.session.send_request(...)`、一次徵詢（elicitation）），會**讓連線死結**：你在等的回應永遠讀不到。射後不理的通知則沒問題。

## 唯一一個預設就啟用的中介軟體 {#the-one-middleware-that-ships-on-by-default}

SDK 只附帶一個中介軟體，而且它已經在伺服器的清單上了：為每則訊息發出一個 OpenTelemetry span 的那一個。不需要自己附加，大多數時候也不用去想它。在安裝匯出器之前它什麼都不做，而且有自己的頁面：**[OpenTelemetry](../run/opentelemetry.md)**。

!!! info
    如果寫過 ASGI 中介軟體，這個形狀你已經認得。Starlette 的 `(scope, receive, send)` 變成了 `(ctx, call_next)`，而且它在傳輸**之後**執行，處理的是解碼後的訊息而不是原始的 HTTP 請求。兩者可以組合：掛在 `streamable_http_app()` 上的 Starlette 中介軟體看到的是 HTTP；這裡看到的是 MCP。

## 重點回顧 {#recap}

* 中介軟體是 `async (ctx, call_next) -> result`，以 `MCPServer(middleware=[...])` 傳入（或附加到 `mcp.middleware`），在低階的 `Server` 上則附加到 `server.middleware`。
* 它包住**每一則**傳入的訊息（`server/discover`、`initialize`、請求、通知、未知的方法），並由最外層開始執行。
* 用 `ctx.request_id is None` 區分通知和請求。
* 不呼叫 `call_next` 改為引發例外，就能拒絕一則訊息；連線會存活下來。
* SDK 自己的 OpenTelemetry 追蹤也是一個中介軟體，已經在清單上。請見 **[OpenTelemetry](../run/opentelemetry.md)**。
* 整個介面都是暫定的。用它來觀察；不要在它上面蓋東西。

以上就是包住請求的一切。至於請求到底能不能執行，則由 **[授權](../run/authorization.md)** 決定。
