---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# 取消 {#cancellation}

用戶端可以放棄一次呼叫：使用者按了停止，或是逾時時間到了。

這時 SDK 會**取消你的處理函式**。它正在等待的那個 `await` 會引發例外，函式逐層退出，它回傳的任何東西都不會送出。大多數處理函式不需要為此做任何事。

有兩種需要：有東西要清理的處理函式，以及用普通 `def` 寫的處理函式。

## 在 `async def` 工具中清理 {#clean-up-in-an-async-def-tool}

把清理工作放進 `finally`：

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* 不論工具怎麼結束，`finally` 都會執行：正常回傳、引發例外，或是被取消。
* 需要 `await` 的清理工作要加上 `shield=True`。在已取消的處理函式裡，之後的每個 `await` 也都會引發例外，所以少了這層保護，`release_hold` 會在第一行就停住。
* 受保護的區塊無法被任何東西取消，所以要給它一個時間限制。這裡是 `5` 秒。

!!! tip
    用 `finally`，不要用 `except`。清理完成後，取消必須繼續往上傳遞，而 `finally` 會放行。

## 在普通 `def` 工具中提早停止 {#stop-early-in-a-plain-def-tool}

普通的 `def` 工具在執行緒中執行，而執行緒無法從外部中斷。工具必須自己詢問：

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` 在呼叫仍有效時什麼都不做，一旦呼叫被取消就會引發例外。在每個工作單元之間呼叫它。
* 這裡的清理工作同樣放在 `finally` 裡。執行緒裡不會有任何 await，所以不需要保護。
* 從不詢問的 `def` 工具會一路執行到結束，結果則被丟棄。

## 適用範圍 {#where-it-applies}

提示詞和資源函式被取消的方式和工具完全相同。

在 stdio 和 Streamable HTTP 上的運作方式相同。使用這個 SDK 的 `Client` 時，放棄指的是取消正在等待 `call_tool` 的任務，或是讓它的 `read_timeout_seconds` 時間用完。

!!! warning
    有兩個 Streamable HTTP 選項會讓處理函式無從得知取消：`2026-07-28` 連線上的 `json_response=True`，以及舊版連線上的 `stateless_http=True`。這時不論用戶端做了什麼，處理函式都會執行到結束。

## 重點回顧 {#recap}

* 用戶端放棄呼叫時，SDK 會取消處理函式：工具、提示詞或資源都一樣。
* `async def`：在 `finally` 裡清理，需要 await 的清理工作放進 `anyio.move_on_after(seconds, shield=True)`。
* 普通 `def`：在工作單元之間呼叫 `anyio.from_thread.check_cancelled()`，否則工具會執行到結束。清理用一般的 `finally` 即可。
* `json_response=True`（新版連線）和 `stateless_http=True`（舊版連線）會關閉取消功能。

進度與取消是執行中的工具和它的**呼叫端**之間的事。它為**你**這個伺服器操作者寫下的記錄，走的是另一個管道：**[記錄](logging.md)**。
