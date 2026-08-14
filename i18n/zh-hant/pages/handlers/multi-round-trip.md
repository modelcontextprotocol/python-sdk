---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# 多輪往返請求 {#multi-round-trip-requests}

有時候工具沒辦法在一次往返內完成。它需要某個只有使用者手上才有的東西：一個選擇、一個確認、一組憑證。

在 2026-07-28 之前，伺服器靠**回頭呼叫**來取得：在處理原本那個請求的途中，自己對用戶端開一個請求（一次徵詢（elicitation）、一次取樣（sampling）呼叫）。2026-07-28 規格淘汰了這條反向通道（back-channel）。

現在，伺服器改成**回傳**。

## 回傳，不要回頭呼叫 {#return-dont-call-back}

伺服器用 **`InputRequiredResult`** 而不是 `CallToolResult` 來回應 `tools/call`。其中兩個欄位負責主要的工作：

* **`input_requests`**：伺服器還需要什麼，以 dict 表示，鍵是伺服器自己取的名稱。每個值是 `ElicitRequest`、`CreateMessageRequest` 或 `ListRootsRequest`。
* **`request_state`**：一個不透明的權杖。用戶端在重試時原封不動地送回來。會讀它的只有你的伺服器。

用戶端逐一滿足這些請求，然後**再次呼叫同一個工具**，把答案放在 `input_responses`，權杖放在 `request_state`。這時伺服器拿到了原本缺的東西，回傳一般的 `CallToolResult`。

整個協定就這樣。每一段都是用戶端送往伺服器的普通請求，從來沒有東西反方向流動。

## 伺服器端 {#the-server-side}

在 `@mcp.tool()` 上很少需要自己動手組這個：宣告一個相依性來詢問使用者（`Elicit`）、對用戶端的 LLM 取樣（`Sample`），或列出它的根目錄（roots，`ListRoots`），SDK 就會替你回傳 `InputRequiredResult`；這種寫法請見 **[相依性](dependencies.md)** 頁面。兩種寫法不能混用：一次呼叫只有一條 `input_responses`／`request_state` 通道，所以用了 `Resolve(...)` 參數的工具，不能再從函式本體回傳 `InputRequiredResult`。宣告了 `InputRequiredResult` 回傳型別的會在註冊時被拒絕（`InvalidSignature`），沒宣告卻回傳的則會在執行時讓呼叫失敗。手動的寫法是**低階** `Server`，它的 `on_call_tool` 處理函式可以回傳兩種結果型別中的任一種：

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` 的型別標註是 `-> CallToolResult | InputRequiredResult`。回傳第二種，就是伺服器端全部的 API。
* 第一次呼叫時 `params.input_responses` 是 `None`，所以守衛條件成立，處理函式改成提問而不是作答。
* 重試時，用戶端送來的 `ElicitResult` 就放在伺服器當初在 `input_requests` 裡用的**同一個鍵**（`"region"`）底下。

那個檔案裡其他的東西（明確寫出的 `input_schema`、手動組出的 `CallToolResult`）都是一般的低階 `Server`，在 **[低階 Server](../advanced/low-level-server.md)** 有說明。這一頁只多加了第二種回傳型別。

## 不只是工具 {#beyond-tools}

`tools/call` 並不特別：在 2026-07-28，伺服器也可以用同樣的方式回應 `prompts/get` 和 `resources/read`。在 `MCPServer` 上，`@mcp.prompt()` 函式（或 `@mcp.resource()` 的**範本**函式）自己回傳 `InputRequiredResult`，並在重試時從 Context 讀取答案：

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* 第一輪回傳 `InputRequiredResult`。重試時，`ctx.input_responses` 在同樣的鍵底下放著答案，函式就回傳它平常的結果——這裡是提示詞訊息，若是範本資源則是資源內容。
* 你設定的 `request_state` 在上線路之前會先密封，回送時會驗證，和伺服器上其他東西一樣；下方的 **[保護 `requestState`](#protecting-requeststate)** 說明密封帶來什麼保障，以及什麼時候需要設定金鑰。
* `@mcp.tool()` 函式在相依性寫法不合用時，也可以用同樣方式直接回傳這個結果。
* 靜態的 `@mcp.resource()` 函式不參與：它們不接收 `Context`，所以永遠讀不到重試的內容。只有範本資源可以提問。
* 下方的世代規則照樣適用：在 2026 之前的工作階段（session）上回傳 `InputRequiredResult`，就是那則警告所描述的 `-32603`。

## 用戶端 {#the-client-side}

`Client` 會替你執行這個迴圈。

註冊伺服器可能會用到的回呼（`elicitation_callback`、`sampling_callback`、`list_roots_callback`），然後呼叫工具。收到 `InputRequiredResult` 時，`Client` 把 `input_requests` 裡的每一筆分派給對應的回呼，帶著答案和原樣送回的 `request_state` 重試，一直持續到拿回 `CallToolResult` 為止：

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* 那個 `elicitation_callback`，和 2026 之前的伺服器透過反向通道送出 `elicitation/create` 時會觸發的是同一個。`sampling_callback` 之於 `sampling/createMessage`、`list_roots_callback` 之於 `roots/list` 也一樣：在 2026-07-28，獨立的伺服器→用戶端 RPC 已經不存在，但完全相同的 `ElicitRequest`／`CreateMessageRequest`／`ListRootsRequest` 酬載改搭在 `input_requests` 裡，分派到同樣這三個回呼。一組回呼同時服務兩個世代。
* `call_tool` 回傳的是普通的 `CallToolResult`。中間那幾輪對呼叫端來說是看不到的。
* `get_prompt` 和 `read_resource` 驅動的也是同一個迴圈。

!!! check
    不註冊回呼的話，迴圈在第一輪就會失敗：SDK 的替身回呼對每個徵詢都回以錯誤，`call_tool` 會引發 `MCPError`，訊息是「Elicitation not supported」。

迴圈是有上限的。`Client(..., input_required_max_rounds=10)` 是預設的上限；伺服器若超過這個次數還繼續回傳 `InputRequiredResult`，`call_tool` 就會引發例外。如果某一輪只帶 `request_state` 而沒有 `input_requests`，`Client` 會先稍微睡一下（從 50 ms 開始加倍，最多 250 ms）再重試，這樣只是在說「還沒好」的伺服器就不會被忙碌輪詢。

### 自己驅動迴圈 {#driving-the-loop-yourself}

對單一處理程序的用戶端來說，自動迴圈就夠了。遇到以下情況則改成自己掌握迴圈：

* 用戶端是**分散式**的：把問題呈現給使用者的處理程序，和呼叫 `call_tool` 的不是同一個，所以重試是由另一個 worker 發出。`request_state` 就是你經由自己的儲存機制、帶著跨越那條邊界的可持久化權杖，而 `input_responses` 則是另一邊連同它一起送回來的東西。
* 想要**檢視**每一輪：記錄或稽核每一筆 `input_requests`、拒絕某些種類的請求，或在各段之間套用自己的退避策略。
* 想要的是**實際時間**上限而不是輪數上限：用 `anyio.fail_after(...)` 包住自己的迴圈，而不是依賴 `input_required_max_rounds`。

往下改用底層的工作階段，在那裡 `allow_input_required=True` 會直接把聯集型別交給你：

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` 把回傳型別放寬成 `CallToolResult | InputRequiredResult`。`isinstance` 負責把它收窄回來。
* `request_state` 現在在你手上。在各段之間把它寫下來，對話就能從全新的處理程序接續。
* 對 `input_requests` 裡的每一筆，都要在 `input_responses` 的**同一個鍵**底下放一個 `InputResponse`。`fulfil` 是放你的 UI 的地方；這個範例把答案寫死了。
* 每一段都是同一個工具名稱、同樣的 `arguments`。重試是把原本的呼叫再做一次，不是新的方法。

## 保護 `requestState` {#protecting-requeststate}

上面所有內容都把 `request_state` 當作一個回音，在線路上它也確實只是如此。但用戶端在各段之間持有它（跨處理程序把它寫下來，正是上一節所認可的做法），所以送回來的東西是**用戶端提供的輸入**：它可能被修改、已經過期，或根本是從另一次呼叫挪過來的。只要這個狀態會影響授權、資源存取或商業邏輯，規格就要求伺服器對它做完整性保護，並在驗證失敗時拒絕該輪。

`MCPServer` 預設就會保護它。每個伺服器都用處理程序啟動時產生的金鑰，密封送出的 `requestState` 並驗證每一個回音，解析器的狀態和手動組的狀態都一樣。不需要設定任何東西，寫明文、讀明文；線路上永遠只帶一個不透明的加密權杖。

預設金鑰與處理程序同生共死，這是部署到超過單一處理程序之前唯一必須知道的事：

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **預設（不做設定）**適合單一處理程序：stdio，或剛好一個 HTTP worker。重試如果落到另一個 worker、負載平衡器後的另一個實例，或重新啟動後的同一台伺服器，密封它的金鑰是那個處理程序沒有的——用戶端會收到下方那則固定的拒絕訊息，必須從頭開始整個流程。
* 只要重試可能到達**另一個實例**（多 worker 的 `uvicorn`、負載平衡的 HTTP）或必須撐過重新啟動，就必須設定 **`keys=[...]`**：每個實例都能驗證任何兄弟實例簽發的東西。機制相同，只是用你的祕密金鑰取代自動產生的。
* 若要用自己的加密機制，例如 KMS 或既有的權杖服務，改傳 `RequestStateSecurity(codec=...)` 而不是 `keys`；下方的 **[自備加密](#bring-your-own-crypto)** 說明其契約。

### 密封裡帶了什麼 {#what-the-seal-carries}

不論是預設還是自行設定，線路上的 `requestState` 都是經過加密與認證的權杖。你的程式碼永遠看不到它：處理函式和解析器寫明文、讀明文（`ctx.request_state`）；SDK 在送出時密封、收進來時驗證。除了完整性之外，每個權杖還綁定到：

* **一段時間窗口。** 每一輪都會用新的到期時間重新密封，所以 `RequestStateSecurity(ttl=...)`（預設 600 秒）限制的是每一輪的思考時間，而不是整個流程。
* **經過驗證的主體。** 當請求帶有 SDK 驗證過的 OAuth 存取權杖時，狀態會綁定到權杖的用戶端、簽發者和 subject：為某個使用者簽發的狀態換到另一個使用者底下就會失敗，即使兩個使用者共用同一個 OAuth 用戶端。驗證器若不提供 subject，綁定就退化成只剩用戶端身分，而在以 URL 為基礎的用戶端 ID 之下，這個身分是該用戶端軟體的所有使用者共用的。當驗證在 SDK 之外終結（前置代理），或傳輸未經驗證時，沒有主體可綁，這項檢查就不起作用，除非 `RequestStateSecurity(bind_principal=...)` 從你自己的身分訊號提供一個。不論權杖驗證器提供哪些組成，都必須前後一致地提供：驗證器如果在某些請求附上 subject、在其他請求省略，主體就在流程中途改變，進行中的各輪會被拒絕。
* **原始請求。** 方法、工具或提示詞名稱（或資源 URI），以及引數的摘要。把權杖拿去對另一個工具、不同的引數或不同的方法重放，都會失敗。
* **問出的確切問題。** 每個解析器的答案都釘在用戶端當時看到的、已轉譯好的問題上，無論是答案剛送達的那一輪，還是之後重用已記錄的答案時。重新部署時若改了訊息措辭或改了 schema，伺服器會重新提問，而不是吃下一個過時的答案。同樣的釘法也會反過來作用：訊息要從工具的引數推導，不要從每次呼叫各異的資料推導。用時間戳記或即時匯率組出來的訊息每一輪轉譯出來都不一樣，於是每個已記錄的答案看起來都過時，伺服器會一直重新提問，直到用戶端的輪數上限結束這次呼叫。

這些全都是 SDK 的工作，不是你的；如果自備 codec，也不是 codec 的。

### 輪替金鑰 {#rotating-keys}

`keys[0]` 負責密封新的狀態；清單裡的每一把金鑰都能驗證。零停機輪替分三個階段，每一階段都要完全推出後才進入下一個：

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

千萬不要先升格簽發用的金鑰：用某些實例還無法驗證的金鑰簽發，會在推出途中讓進行中的各輪掉落。

金鑰的作用範圍是單一服務。密封的信封也帶著伺服器名稱作為 audience 宣告，所以由恰好共用同一個祕密的另一個服務所簽發的權杖，照樣會被拒絕。這個宣告的辨識度取決於名稱，所以給了明確策略的伺服器必須有真正的名稱，或設定 `RequestStateSecurity(audience=...)`——沒有名稱的會在建構時引發例外。`audience=` 也適用於刻意設計的多服務拓撲，也就是某個服務必須接受另一個服務簽發的狀態的情形。（不做設定的預設情況不受此限：它的金鑰從不離開處理程序，audience 宣告沒什麼可補充的。）

### 自備加密 {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` 接受任何具有 `seal(bytes) -> str` 與 `unseal(str) -> bytes`、且對任何不是自己簽發的權杖會引發 `InvalidRequestState` 的物件。典型的形式是搭配 KMS 的信封加密：啟動時解包一次資料金鑰，之後每個權杖的加解密都留在本機：

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL、主體綁定和請求綁定都**不是** codec 的工作：不論哪個 codec，SDK 都會在 `seal` 之前把它們蓋進酬載，在 `unseal` 之後重新驗證。codec 唯一的義務是完整性（被竄改就引發例外），以及最好還有機密性。

### 驗證失敗時 {#when-verification-fails}

每一個進來的失敗，不論是被竄改、過期、對不同的請求或主體重放，還是用這台伺服器不認得的金鑰密封，都得到同一個回答：

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

所有原因都是同一則固定訊息，所以線路上永遠看不出是哪項檢查失敗；真正的原因寫進伺服器記錄。`tools/call`、`prompts/get` 和 `resources/read` 上每一個進來的 `requestState` 都會檢查，連送往從不簽發狀態的處理函式的也包括在內。實務上最常見的拒絕不是攻擊者，而是預設的處理程序內金鑰碰上重新啟動之前或來自另一個實例的重試；用戶端重新開始流程，而在這件事要緊時，`keys=[...]` 就是解法。

### 手動組的狀態 {#hand-built-state}

你自己設定的 `request_state`（從工具、提示詞或資源範本函式回傳 `InputRequiredResult`）和解析器狀態由同一套機制密封與驗證，程式碼一行都不用改：寫明文、讀明文，上面每一項綁定都適用。

即使設定好了，SDK 唯一無法替你釘住的是問題的身分：它不知道你狀態裡的某個答案屬於**你的**哪一個問題。如果你以問題為鍵存放答案，就在狀態裡放進自己的問題識別碼，並在重試時檢查它。

低階 `Server` 是不附電池的那一層：和 `MCPServer` 不同，在你自己加上那道邊界之前什麼都不會密封，而在那之前你的 `request_state` 會照寫出來的樣子原封不動上線路。那一行的選用寫法請見 **[低階 Server](../advanced/low-level-server.md#the-other-handlers)**。

## 2026-07-28 的結果型別 {#a-2026-07-28-result}

`InputRequiredResult` 只存在於協定版本 **2026-07-28**。記憶體內的 `Client(server)` 會替你協商；走線路時，`mode="auto"` 會探知它。連線之後，`client.protocol_version` 會告訴你拿到的是什麼。

!!! warning
    2026 之前的工作階段沒有地方放 `InputRequiredResult`。在 `mode="legacy"` 的連線上從處理函式回傳一個，runner 無法把它序列化成協商好的版本；用戶端會拿回 `-32603`「Handler returned an invalid result」錯誤。同時服務兩個世代的伺服器，必須先檢查 `ctx.protocol_version` 再動用它。

!!! info
    **URL 模式的徵詢**在 2026 連線上正是搭著這套機制。`input_requests` 裡的那一筆是一個 params 為 `ElicitRequestURLParams` 的 `ElicitRequest`；使用者完成帶外流程後，用戶端重試這次呼叫。同一個迴圈，沒有新的 API。高階伺服器那一半請見 **[徵詢](elicitation.md)**。

## 重點回顧 {#recap}

* 在 2026-07-28，呼叫途中需要輸入的伺服器會**回傳** `InputRequiredResult`，從不向用戶端開請求。
* `input_requests` 是它需要的東西。`request_state` 是只有伺服器會讀的不透明接續權杖。
* `Client` 替你執行重試迴圈：註冊 `elicitation_callback`／`sampling_callback`／`list_roots_callback`，`call_tool` 就回傳普通的 `CallToolResult`。`input_required_max_rounds`（預設 10）替它設上限。
* 要檢視或持久化各輪，用 `client.session.call_tool(..., allow_input_required=True)`，自己掌握 `while isinstance(result, InputRequiredResult)` 迴圈。
* 在 `@mcp.tool()` 上，會詢問使用者的相依性替你產出這個結果（**[相依性](dependencies.md)**）；**低階** `Server` 是手動的寫法。
* 提示詞和資源也參與：`@mcp.prompt()` 或範本 `@mcp.resource()` 函式自己回傳 `InputRequiredResult`，重試時讀 `ctx.input_responses`。
* `requestState` 回來時是用戶端提供的輸入，所以 `MCPServer` 預設就用處理程序內的金鑰密封它——解析器狀態和手動組的狀態都一樣；多實例部署要傳入 `RequestStateSecurity(keys=[...])`（或自訂 codec），好讓每個實例都能驗證兄弟實例簽發的東西。密封把每個權杖綁定到一段時間窗口、原始請求，以及經過驗證的主體——條件是請求帶有 SDK 驗證過的驗證資訊，或由 `bind_principal=` 提供你自己的身分訊號（**[保護 `requestState`](#protecting-requeststate)**）。

這就是取代伺服器主動發起的取樣、以及其餘推送式反向通道的機制；請見 **[已棄用的功能](../deprecated.md)**。
