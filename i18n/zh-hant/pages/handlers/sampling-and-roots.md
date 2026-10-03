---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# 取樣與根目錄 {#sampling-and-roots}

處理函式還可以向連線的用戶端多要兩樣東西：由用戶端自己的模型產生的生成結果，也就是**取樣**（sampling）；以及用戶端的工作區資料夾，也就是**根目錄**（roots）。

兩者在 SDK 支援的每個協定版本上都還能用。但在以它們為基礎做設計之前，先讀一下這段警告：

!!! warning "已於 2026-07-28 規格中棄用"
    取樣和根目錄自 `2026-07-28` 起已棄用（[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)）。它們仍然完全可用，並且會在規格中至少保留 12 個月，之後才可能被移除；但新的實作不應該建立在它們之上。建議的遷移方式：不要用取樣，改為直接整合 LLM 供應商的 API；不要用根目錄，改為透過工具參數、資源 URI 或伺服器設定來傳入目錄。整個 SDK 的清單在 **[已棄用的功能](../deprecated.md)**。

## 取樣：借用用戶端的模型 {#sampling-borrow-the-clients-model}

解析器回傳 `Sample(...)`，工具就會收到生成結果，走的是和 **[相依性](dependencies.md)** 中執行 `Elicit` 相同的相依性機制：

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` 對應 `sampling/createMessage` 的參數。注入的值是用戶端的 `CreateMessageResult`；如果傳入 `tools` 或 `tool_choice`，則會變成 `CreateMessageResultWithTools`。
* 用戶端必須宣告了 `sampling` 能力（如果傳入 `tools` 或 `tool_choice`，則是 `sampling.tools`）。如果沒有，呼叫會以 `-32021` 協定錯誤失敗，而不是送出一個用戶端無法處理的請求。沒有反向通道（back-channel）的 2026 之前的工作階段（session）則會以它一貫的「沒有反向通道」錯誤失敗，因為根本沒有通道可送。
* 在 `2026-07-28`，請求是在多輪往返（multi-round-trip）流程中傳遞的（**[多輪往返請求](multi-round-trip.md)**）；在 `2025-11-25` 則是對用戶端發出的獨立請求。兩種情況下程式碼都一樣，但要注意多輪往返的規則：請求在各輪重試之間必須呈現得完全相同，所以只能用工具的引數和其他穩定的資料來建構它。
* 不要動 `include_context`：`"none"` 以外的值本身也已棄用（SEP-2596），而且需要一個幾乎沒有用戶端會宣告的能力。

## 根目錄：這個該放哪裡？ {#roots-where-should-this-go}

根目錄是用戶端表示伺服器可以操作的資料夾。它們是參考用的指引，不是存取控制機制。解析器回傳 `ListRoots()`：

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* 注入的 `ListRootsResult` 帶有一個 `Root` 清單：每個包含一個 `file://` URI 和一個選填的顯示名稱。
* 把關條件和取樣相同：沒有宣告 `roots` 能力時，呼叫會以 `-32021` 失敗，而不會送出請求。

在線路的另一端，用戶端用它已有的回呼來回應這兩種請求：`sampling_callback` 和 `list_roots_callback`，說明見 **[用戶端回呼](../client/callbacks.md)**。

## 在 2025 世代的連線上 {#on-2025-era-connections}

`ctx.session.create_message(...)` 和 `ctx.session.list_roots()` 仍然存在，供直接操作工作階段的程式碼使用。它們只在有反向通道的地方才能運作（2025 世代、非無狀態的連線），而且呼叫時會引發棄用警告。上面的解析器標記才是受支援的形式：它們會依協商出的版本挑選傳遞方式，也不會發出警告。

## 重點回顧 {#recap}

* 從解析器回傳 `Sample(...)` 或 `ListRoots()`；工具會像收到其他相依性一樣收到 `CreateMessageResult` 或 `ListRootsResult`。
* 用戶端必須宣告對應的能力，否則呼叫會以 `-32021` 失敗，而不會送出請求。
* 兩項功能在 `2026-07-28` 都已棄用：目前完全可用，但不適合新設計。優先選擇供應商 API 而非取樣，優先選擇明確的參數而非根目錄。

回報慢速工具的進度：**[進度](progress.md)**。
