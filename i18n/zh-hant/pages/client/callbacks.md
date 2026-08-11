---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# 用戶端回呼 {#client-callbacks}

MCP 裡幾乎每一個請求都是單向的：從用戶端到伺服器。

伺服器也可以反過來向**用戶端**要東西：向使用者提問、對使用者的模型取樣（sampling）、列出使用者的工作區資料夾。要回應這些請求，就把**回呼**傳給 `Client(...)`。

## 會發問的伺服器 {#a-server-that-asks}

下面這個伺服器的工具沒辦法自己完成：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` 會**向用戶端**送出一個 `elicitation/create` 請求，然後等待。
* 在有人（填表單的人，或是你的程式碼）提供 `name` 之前，這個工具不會回傳。

那是伺服器那一半，由 **[徵詢（elicitation）](../handlers/elicitation.md)** 頁面負責說明。這一頁講的是線路的另一端。

## 徵詢回呼 {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* 徵詢回呼的形式是 `async (context, params) -> ElicitResult`。
* `params.message` 是問題本身。`params.requested_schema` 是伺服器想要的答案的 JSON Schema。真正的用戶端會依它繪製出表單；這個範例則是自動填入。
* 回傳 `ElicitResult(action="accept", content={...})`，或 `action="decline"`，或 `action="cancel"`。除此之外唯一的選項是 `ErrorData(...)`，它會拒絕這個請求，讓整個呼叫失敗。
* `context` 是一個 `ClientRequestContext`：包含目前的 `session`、伺服器的 `request_id`，以及它附上的任何 `meta`。

!!! tip
    `params` 是兩種徵詢模式的聯集。這裡的 `params.mode` 是 `"form"`；`"url"` 請求帶的是 `params.url` 而不是 schema。同一個回呼處理兩種模式，依 `params.mode` 分支即可。完整的寫法請見 **[徵詢](../handlers/elicitation.md)**。

### 試試看 {#try-it}

呼叫 `issue_card`，觀察兩端的情況。

回呼會收到伺服器的問題，而且已經解析好了：

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

它回答之後，`ctx.elicit(...)` 在工具內部恢復執行，工具隨即完成：

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

你送出一個 `tools/call`，伺服器回送一個 `elicitation/create`，由你的函式回答，全都發生在同一次工具呼叫之內。

!!! info
    `Client(...)` 呼叫上的 `mode="legacy"` 是真的有作用。預設情況下 `Client(...)` 會協商出現代的協定路徑，而這條路徑沒有讓伺服器向用戶端發請求的反向通道（back-channel）：`ctx.elicit` 在你的回呼有機會執行之前就失敗了。決定這件事的不是傳輸方式，而是協商出來的協定，記憶體內和透過 URL 連線都一樣。只要用戶端必須回應這類請求，就固定用 `mode="legacy"`；這一頁背後的每個測試都是這樣做的。完整說明請見 **[協定版本](../protocol-versions.md)**。

    在 2026-07-28 的工作階段（session）上，回呼並沒有失效，只是餵給它的方式不同：當工具回傳帶有 `ElicitRequest` 的 `InputRequiredResult` 時，`Client` 會把那個項目分派給同一個 `elicitation_callback`，並替你重試這次呼叫。這個流程就是 **[多輪往返（multi-round-trip）請求](../handlers/multi-round-trip.md)**。

## 回呼就是能力 {#a-callback-is-a-capability}

你從來沒有告訴伺服器你的用戶端能回應徵詢請求。是 SDK 說的。

用戶端連線時會宣告自己的 `capabilities`，正好是伺服器那一份的鏡像。這個物件不用你寫。**註冊回呼就是宣告。**

| 你傳入 | 用戶端宣告 |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| 一個都不傳 | `{}` |

取樣的子能力是唯一需要細分的地方：如果你的取樣器會處理 `tools` / `tool_choice` 參數，就在 `sampling_callback` 旁邊一併傳入 `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())`。伺服器必須先看到 `sampling.tools` 被宣告，才能送出這些參數。

`logging_callback` 和 `message_handler` 不在表中。它們處理的是通知，而通知不需要能力。

伺服器用 `ctx.session.check_client_capability(...)` 把這份宣告讀回來。加一個這樣做的工具：

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

只帶 `elicitation_callback` 連線並呼叫它：

```python
result.structured_content  # {'result': ['elicitation']}
```

三個回呼都傳，會得到 `['elicitation', 'sampling', 'roots']`。一個都不傳，會得到 `[]`。

!!! check
    現在故意做錯：**不帶** `elicitation_callback` 連線，照樣呼叫 `issue_card`。

    伺服器的 `elicitation/create` 請求還是會送到你的用戶端，而 SDK 會替你回應，用的是錯誤，因為你從沒說過自己能處理它。這個錯誤會拖垮整個呼叫。`call_tool` 不會回傳 `is_error` 結果，而是引發例外：

    ```text
    MCPError: Elicitation not supported
    ```

    這是協定錯誤（`-32600`，*invalid request*），不是工具錯誤：沒有任何東西可以讓模型讀了再重試。這就是 `client_features` 值得有的原因：行為良好的伺服器會先檢查再發問。

## 已棄用的那一對 {#the-deprecated-pair}

`sampling_callback` 回應 `sampling/createMessage`：伺服器請**你的**模型生成一些內容。`list_roots_callback` 回應 `roots/list`：伺服器詢問它可以在哪些目錄裡工作。

兩個都能用。兩個都遵守上面的規則。而兩個服務的 RPC 都是 **2026-07-28 規格移除的**：現代的伺服器不會在請求途中回頭呼叫你的用戶端，而是把請求當成工具結果的一部分交還給你（**[多輪往返請求](../handlers/multi-round-trip.md)**）。回呼本身並沒有失效。當 `InputRequiredResult` 帶著 `CreateMessageRequest` 或 `ListRootsRequest` 時，`Client` 的自動迴圈會把它分派給你在這裡註冊的同一個 `sampling_callback` 或 `list_roots_callback`。完整清單請見 **[已棄用的功能](../deprecated.md)**。

要和還沒升級的伺服器溝通，你仍然需要這些回呼。簽章如下：

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* 取樣回呼會收到完整的 `CreateMessageRequestParams`（`messages`、`model_preferences`、`max_tokens`），並回傳 `CreateMessageResult`。模型由**你**來執行，怎麼執行都行；SDK 只負責傳遞請求。
* 根目錄（roots）回呼完全不接受參數，回傳 `ListRootsResult`。
* 兩者都可以改為回傳 `ErrorData(...)` 來拒絕。

把它們傳給 `Client(...)` 的方式和 `elicitation_callback` 完全一樣。

## 通知回呼 {#the-notification-callbacks}

還有兩個。兩個都不宣告任何東西。

`logging_callback` 會收到伺服器送出的 `notifications/message`，型別是 `LoggingMessageNotificationParams`（`level`、`logger`、`data`）。協定記錄本身已被 2026-07-28 規格棄用（該怎麼改做請見 **[記錄](../handlers/logging.md)**），所以這個回呼是為了還在送出它的伺服器而存在。在 2026 世代的連線上，光有回呼什麼都收不到，因為 2026 的伺服器只會把記錄訊息送給主動選擇接收的請求：把 `log_level="info"`（或其他層級）傳給 `Client(...)`，就會在每個請求上蓋上這個選擇，並收到該層級以上的訊息。2026 之前的伺服器會忽略它，維持原本的 `logging/setLevel` 行為。

`message_handler` 是總攬一切的那個：工作階段浮現的每一個伺服器通知都會送到它（同時也送到各自專屬的回呼），在以串流為基礎的傳輸方式上，每一個傳輸層級的 `Exception` 也會。有兩種永遠不會：`notifications/cancelled` 由 SDK 直接套用而不浮現，而正在運作的 `listen()` 串流的訂閱確認則由那個串流自己消化。把這個參數註記為 `IncomingMessage`（`ServerNotification | Exception`，從 `mcp.client` 匯出）。唯一值得知道的寫法是 `if isinstance(message, Exception): raise message`，這樣連線斷掉時會大聲失敗，而不是悄悄消失。

## 重點回顧 {#recap}

* 伺服器可以向用戶端送出請求。用傳給 `Client(...)` 的回呼來回應它們。
* 徵詢回呼是現行的那一個：`async (context, params) -> ElicitResult`，一個函式同時處理 form 和 URL 模式。
* **註冊回呼就是宣告能力。**沒有它，SDK 會替你拒絕伺服器的請求，整個呼叫以 `MCPError` 失敗。
* 伺服器在發問之前用 `ctx.session.check_client_capability(...)` 先確認。
* `sampling_callback` 和 `list_roots_callback` 的運作方式相同，但服務的是已棄用的功能；現代的伺服器改用多輪往返請求。
* `logging_callback` 和 `message_handler` 接收通知。它們不宣告任何東西。

`Client(...)` 的第一個引數是一個傳輸物件。**[用戶端傳輸方式](transports.md)** 涵蓋了每一種。
