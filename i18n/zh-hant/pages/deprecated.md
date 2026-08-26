---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# 已棄用的功能 {#deprecated-features}

2026-07-28 規格讓五樣東西退場。SDK 仍然實作了其中每一項，而每一項現在都帶有**棄用警告**。另外有一個 SDK 輔助函式是因為自身的原因棄用，列在[最後](#deprecated-sdk-helpers)。

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

## 舊版工作階段上的 `ping` {#ping-on-a-legacy-session}

**ping** 是一個空的請求，任何一方都可以送出，用來確認對方還有回應。2026-07-28 規格移除了它（[SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)）：現代用戶端送出的每個請求本身就已經證明伺服器還在，而現代伺服器也沒有通道可以送出 ping。兩個 SDK 方法在交握世代的工作階段上仍然有效。從用戶端：

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

從伺服器端，在任何處理函式內：

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` 每次呼叫都會發出 `MCPDeprecationWarning`。在預設（`2026-07-28`）的連線上，伺服器則改為回應 `MCPError: Method not found`。
* `ctx.session.send_ping()` 不帶警告。在現代連線上，它會和其他任何伺服器發起的請求一樣，引發沒有反向通道（back-channel）的錯誤。
* 兩邊都不需要註冊任何東西來回應 ping。

## 根目錄變更通知 {#roots-change-notifications}

宣告了根目錄能力的 2025 世代用戶端，可以送出 `notifications/roots/list_changed` 告訴伺服器它的工作區資料夾變了；伺服器的回應是再次請求 `roots/list`。2026-07-28 規格把這個通知連同其餘推送式的根目錄流程一起移除。在用戶端，傳入 `list_roots_callback=`（**[用戶端回呼](client/callbacks.md)**）就是宣告 `"roots": {"listChanged": true}` 的那一步，而兌現這個承諾只需要一次呼叫：

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

在伺服器端，接收端的處理函式由低階 `Server` 接手：

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` 是 `list_roots_callback` 回傳的那個清單。`client.send_roots_list_changed()` 會發出警告，而且需要 `mode="legacy"` 的用戶端：在現代連線上，這個通知會被默默丟棄。之後要讓工作階段保持開啟，因為伺服器後續的 `roots/list` 會從這條工作階段送來。
* `MCPServer` 沒有對應這個通知的掛鉤。在低階 `Server` 上，`on_roots_list_changed=` 用來註冊處理函式（同樣已棄用，建構時就會發出警告）。這個通知不帶任何酬載，所以處理函式要呼叫 `ctx.session.list_roots()` 取得新清單。

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
    把過濾器反過來用，就免費得到一個回歸測試。在 pytest 設定的 `filterwarnings` 裡加上 `"error::mcp.MCPDeprecationWarning"`，已棄用的呼叫就會**引發例外**而不是發出警告。一個名為 `old_log`、還在呼叫 `ctx.info()` 的工具會不再通過：呼叫回來時是 `is_error=True`，帶著 `Error executing tool old_log`，而擷取到的伺服器記錄會點名元凶：

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    一行 pytest 設定，已棄用的呼叫就再也沒辦法在不讓測試失敗的情況下溜回程式碼庫。

## 已棄用的 SDK 輔助函式 {#deprecated-sdk-helpers}

這些不是規格變更，只是有了更好替代做法的 SDK 內部實作。它們用同樣的 `MCPDeprecationWarning` 發出警告，並會在 3.0 移除。

| 已棄用項目 | 替代做法 |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | 先 `FuncMetadata.validate_arguments()`，再 `FuncMetadata.call_fn()`。只有直接操作 `FuncMetadata` 的程式碼（例如自訂的 `Tool` 子類別）才會呼叫過它。 |

## 重點回顧 {#recap}

* 2026-07-28 規格棄用了**根目錄**、伺服器發起的**取樣**和協定**記錄**（全部來自 [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)），把**進度**限制為只能從伺服器到用戶端，並移除了 **`ping`**。
* 替代做法那一欄指引你接下來往哪走：取樣和根目錄看 **[多輪往返請求](handlers/multi-round-trip.md)**，記錄看 **[記錄](handlers/logging.md)**，進度看 **[進度](handlers/progress.md)**。`ping` 什麼都不需要。
* 棄用只是勸告性質：線路沒有變更，一切在 2026 之前的工作階段上都能繼續運作，而且你會看到明顯的 `MCPDeprecationWarning`（它是 `UserWarning`，所以預設就會顯示）。
* 取樣和根目錄還額外需要一條反向通道，而 2026-07-28 的工作階段沒有。在現代連線上，它們會先警告，再引發例外。
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` 會讓整個類別靜音；pytest 裡的 `"error::mcp.MCPDeprecationWarning"` 則把它變成測試失敗。
* 有一個 SDK 輔助函式 `FuncMetadata.call_fn_with_arg_validation()` 另外單獨棄用，預計在 3.0 移除。
* 新程式碼不應該建立在這些東西之上。

這份說明文件的其他每一頁教的都是目前的 API。
