---
translation:
  sections: [20541a40dbdd5980, 01262a123ad9501d, 429db5b574a2ac08, 56b2d49da412cb28, 6a1717123fe4513c]
  tool: 1
---
# 已棄用的功能 {#deprecated-features}

2026-07-28 規格讓五樣東西退場。SDK 仍然實作了其中每一項，而每一項現在都帶有**棄用警告**。

下表列出每一項已棄用的功能、它為什麼要退場，以及應該改用的替代做法。

## 哪些已棄用 {#what-is-deprecated}

| 已棄用項目 | 原因 | 替代做法 |
|---|---|---|
| **根目錄（roots）**：`ctx.session.list_roots()`、`client.send_roots_list_changed()`、傳給 `Client(...)` 的 `list_roots_callback=` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) 讓這項能力退場。 | 把路徑當成一般的工具引數或資源 URI 來接收，或是在 `InputRequiredResult` 裡嵌入一個 `ListRootsRequest`（請見 **[多輪往返（multi-round-trip）請求](handlers/multi-round-trip.md)**）。 |
| **伺服器發起的取樣（sampling）**：`ctx.session.create_message()`、傳給 `Client(...)` 的 `sampling_callback=` | SEP-2577 讓這項能力退場。 | 回傳 `InputRequiredResult`，讓用戶端重試這次呼叫（請見 **[多輪往返請求](handlers/multi-round-trip.md)**）。 |
| **協定記錄**：`ctx.log()`、`ctx.debug()`、`ctx.info()`、`ctx.warning()`、`ctx.error()`、`ctx.session.send_log_message()`、`client.set_logging_level()` | SEP-2577 讓這項能力退場。協定內沒有任何東西取代它。 | 用一般的 `import logging` 輸出到 stderr（請見 **[記錄](handlers/logging.md)**）。 |
| **`ping`**：`client.send_ping()` | 從協定中**移除**，而不只是棄用。2026-07-28 裡沒有 `ping` 方法。 | 什麼都不用。它只在 `mode="legacy"` 的連線上有效。 |
| **用戶端到伺服器的進度**：`client.send_progress_notification()` | 2026-07-28 讓進度只能從伺服器送往用戶端。 | 沒有東西要送。**伺服器**用 `ctx.report_progress()` 回報進度（請見 **[進度](handlers/progress.md)**）。 |

從這張表可以看出三件事：

* 根目錄、取樣和記錄是一起的。同一份提案 **SEP-2577** 一次棄用了這三項能力。
* 取樣和根目錄有個更深層的共同問題：它們都是**伺服器**向**用戶端**送出**請求**的地方。2026-07-28 用 **[多輪往返請求](handlers/multi-round-trip.md)** 取代的正是這整個方向。消失的是那些獨立的 RPC 方法（`sampling/createMessage`、`roots/list`，以及推送式的 `elicitation/create`）；`CreateMessageRequest`／`ListRootsRequest`／`ElicitRequest` 這些酬載型別則保留下來，嵌在 `InputRequiredResult.input_requests` 裡，在用戶端會觸發同樣的回呼。
* `ping` 是特例。協定不是棄用它，而是移除它。SDK 的方法仍然會發出警告（訊息寫的是 *removed*，不是 *deprecated*），在現代連線上呼叫它，得到的回應是 *"Method not found"*。

## 棄用只是勸告性質 {#deprecated-is-advisory}

今天什麼都不會壞。

上面每個方法，在任何協商到 **2025-11-25 或更早版本**的工作階段（session）上都能繼續運作。在用戶端固定 `mode="legacy"`，就能得到和 2026 之前完全一樣的行為。線路上沒有任何變更，能力協商也維持不變。

改變的是，每個方法第一次執行時，你會看到一則明顯的警告：

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` 繼承自 `UserWarning`，**不是** `DeprecationWarning`。這是刻意的：Python 的預設過濾器只會在直接以 `__main__` 執行的程式碼裡顯示 `DeprecationWarning`，這就是為什麼函式庫棄用了某樣東西，卻兩年都沒人注意到。這個警告到處都會出現，不需要 `-W` 旗標。

!!! warning
    「勸告性質」到線路為止。取樣和根目錄是伺服器對用戶端的**請求**，而 2026-07-28 的工作階段沒有通道可以承載它。在現代連線上於工具內呼叫 `ctx.session.create_message()`，警告照樣會發出，接著傳送會失敗並出現錯誤：

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    兩個訊號，依這個順序出現。`MCPDeprecationWarning` 在呼叫方法的那一刻就會發出，任何連線都一樣。錯誤則是 SDK 接著嘗試傳送時回傳來的東西。這兩者只有在用戶端註冊了對應回呼的 `mode="legacy"` 連線上，才能從頭到尾正常運作。

## 讓警告靜音 {#silencing-the-warning}

新程式碼裡，不要這麼做。

但如果你維護的伺服器確實在服務 2026 之前的用戶端，它完全有權保持記錄乾淨。在第一個已棄用的呼叫執行之前，先過濾掉這個類別：

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

整個 API 就這樣。沒有逐方法的開關，你也不會想要：只用一個類別的意義在於，一行就能關掉它，一行就能把它叫回來。

!!! check
    把過濾器反過來用，就免費得到一個回歸測試。在 pytest 設定的 `filterwarnings` 裡加上 `"error::mcp.MCPDeprecationWarning"`，已棄用的呼叫就會**引發例外**而不是發出警告。一個名為 `old_log`、還在呼叫 `ctx.info()` 的工具會不再通過，開始回報：

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    一行 pytest 設定，已棄用的呼叫就再也沒辦法在不讓測試失敗的情況下溜回程式碼庫。

## 重點回顧 {#recap}

* 2026-07-28 規格棄用了**根目錄**、伺服器發起的**取樣**和協定**記錄**（全部來自 [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)），把**進度**限制為只能從伺服器到用戶端，並移除了 **`ping`**。
* 替代做法那一欄指引你接下來往哪走：取樣和根目錄看 **[多輪往返請求](handlers/multi-round-trip.md)**，記錄看 **[記錄](handlers/logging.md)**，進度看 **[進度](handlers/progress.md)**。`ping` 什麼都不需要。
* 棄用只是勸告性質：線路沒有變更，一切在 2026 之前的工作階段上都能繼續運作，而且你會看到明顯的 `MCPDeprecationWarning`（它是 `UserWarning`，所以預設就會顯示）。
* 取樣和根目錄還額外需要一條反向通道（back-channel），而 2026-07-28 的工作階段沒有。在現代連線上，它們會先警告，再引發例外。
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` 會讓整個類別靜音；pytest 裡的 `"error::mcp.MCPDeprecationWarning"` 則把它變成測試失敗。
* 新程式碼不應該建立在這些東西之上。

這份說明文件的其他每一頁教的都是目前的 API。
