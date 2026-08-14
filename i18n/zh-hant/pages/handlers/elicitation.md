---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# 徵詢 {#elicitation}

工具做到一半、只差一個答案時，不一定要就此失敗。

**徵詢（elicitation）** 讓它可以開口問。在工具呼叫進行到一半時，使用者會收到一個問題，而他們的回答會回到同一次函式呼叫裡。

有兩種模式：

* **表單模式**：需要一個值（確認、日期、數量）。你描述欄位，用戶端負責呈現表單。
* **URL 模式**：需要使用者到別的地方去（OAuth 同意畫面、付款頁面）。他們在那裡做的任何事都不會經過協定。

問的方式也有兩種。該優先採用的是**解析器**：把問題掛在參數上，由 SDK 來問，不論哪種連線、不論用戶端說的是哪個協定世代都行。直接的方式 `await ctx.elicit(...)` 是從**伺服器**發往**用戶端**的請求，這條通道只有在舊版連線（規格版本 2025-11-25 或更早）上的用戶端才有。兩種本頁都會介紹，先從解析器開始。

## 用解析器來問 {#ask-with-a-resolver}

決定整個工具能否繼續的問題（「確定嗎？三個符合的帳號要哪一個？」）可以從工具本體抽出來放進**解析器**，由框架替你問。

標註為 `Annotated[T, Resolve(fn)]` 的參數，會在工具本體執行前先執行 `fn` 來填入。解析器已經知道答案時就直接回傳值，否則回傳 `Elicit(...)` 讓框架去問：

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` 依名稱讀取工具自己的 `path` 引數，列出資料夾內容，而且**只在必要時才徵詢**：空資料夾直接解析為 `Confirm(ok=True)`，完全不需要與用戶端往返。
* `delete_folder` 標註的是 `ElicitationResult[Confirm]`，所以框架會注入完整的結果，工具再用 `match` 處理每一種情況：接受並確認、接受但保留（`ok=False`）、拒絕、取消。
* `confirm` 參數永遠不會出現在工具的輸入 schema 裡：`path` 由用戶端提供，`confirm` 由解析器提供。

如果工具不需要分支處理，改為標註未包裝的模型（`Annotated[Confirm, Resolve(confirm_delete)]`）即可：接受時工具會收到模型，拒絕或取消時整個呼叫會以錯誤中止。

解析器在**每一種**連線上都能用。對舊版連線上的用戶端，SDK 會直接把問題送過去；在 **2026-07-28** 連線上，SDK 會把問題從呼叫中**回傳**出去，用戶端下一次嘗試時再帶著答案回來。解析器完全不知道其中的差別；底下發生的事請見**[多輪往返（multi-round-trip）請求](multi-round-trip.md)**。

問問題只是解析器能做的事情之一。通用的機制（不用問就能算出值的相依性、相依性的相依性、模型能提供與不能提供什麼）請見**[相依性](dependencies.md)**頁面。

## 在工具內部問 {#ask-from-inside-the-tool}

工具也可以在自己的本體執行到一半時停下來問。

!!! warning
    `ctx.elicit()` 和 `ctx.elicit_url()` 是從**伺服器**發往**用戶端**的請求，這條通道只有在舊版連線（規格版本 **2025-11-25** 或更早）上的用戶端才有。在 **2026-07-28** 連線上沒有由伺服器發起的請求，所以這些呼叫會失敗。解析器則兩種都能用。完整說明請見**[協定版本](../protocol-versions.md)**。

`await ctx.elicit()` 接受一則訊息和一個 Pydantic 模型：

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** 參數就是讓你能用 `ctx.elicit` 的東西；任何工具都可以接收一個。這個物件有自己的頁面：**[Context](context.md)**。
* `AlternativeDate` 是你想要的答案的 **schema**。
* 這個工具是 `async def`。非如此不可：它會在中途停下來等一個人回答。
* 其他任何日期，工具都會直接回傳。只有在必要時才問。
* 使用者接受的日期會再經過 `book_table` 本身處理一次。回答和其他輸入沒有兩樣：如果替代日期也訂滿了，會再問一次，而不是盲目確認。

### 用戶端收到什麼 {#what-the-client-receives}

用戶端會收到你的訊息，旁邊附上一份從模型產生的 JSON Schema：

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

那份 schema 就是表單。`Field(description=...)` 是標籤；預設值會預先填入輸入框，並讓該欄位變成選填。這和**[工具](../servers/tools.md)**頁面描述工具引數時用的是同一套 Pydantic 轉 JSON Schema 機制。

!!! warning
    徵詢用的 schema 表達能力不如工具的輸入 schema。只能用扁平的基本型別欄位：`str`、`int`、`float`、`bool`，或是字串組成的 `Literal`（會變成 `enum`）。如果在模型裡再放一個模型，`ctx.elicit` 會在送出任何東西給用戶端之前就引發例外：

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    你是在打斷一個正在做事的人。如果答案需要巢狀結構，它本來就該是工具的引數。

### 三種回答 {#the-three-answers}

`result.action` 告訴你使用者做了什麼，可能性恰好只有三種：

* `"accept"`：他們送出了表單。`result.data` 是一個 `AlternativeDate` 實例，已經驗證過。
* `"decline"`：他們說不要。
* `"cancel"`：他們沒有選擇就關掉了問題。

`result.data` 只在 `"accept"` 時存在，這就是範例先檢查 `result.action` 的原因。型別檢查器會強制這個順序：在 `result.action == "accept"` 之後，`result.data` 是 `AlternativeDate`；在那之前，根本沒有 `.data`。

拒絕不是錯誤。拒絕代表什麼由工具決定（這裡是不訂位），然後照常回答模型。

!!! tip
    回答在你的程式碼看到之前，就會先依照模型驗證。用戶端若在 `bool` 欄位送來 `"maybe"`，也不會弄壞你的訂位：呼叫會以 schema 不符的錯誤失敗，你的 `if` 根本不會執行。

## 把使用者送往一個 URL {#send-the-user-to-a-url}

有些東西絕對不能經過模型或用戶端：憑證、卡號、OAuth 同意。遇到這些，你不是要資料，而是請使用者到某個地方去：

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` 接受訊息、要造訪的 **URL**，以及一個你自己選的 `elicitation_id`：任何能在伺服器內識別這次徵詢的字串都行。
* 結果只有一個 action，沒有別的。`"accept"` 代表使用者同意開啟 URL，**不是**代表他們完成了另一頭的事。
* 付款在頻外進行，發生在使用者的瀏覽器和你的金流服務商之間。沒有任何內容會透過 MCP 回來。

看看第二個工具。當伺服器得知頻外流程完成時（webhook、輪詢；這裡用第二個工具來模擬），`ctx.session.send_elicit_complete(...)` 會以同一個 `elicitation_id` 送出 `notifications/elicitation/complete`。用戶端就是靠這個知道可以停止顯示「等待付款中……」。少了它，用戶端只能猜。

## 用戶端這一邊 {#the-client-side}

伺服器負責問。用戶端回答的方式，是把一個 **`elicitation_callback`** 傳給 `Client(...)`：

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 一個回呼處理兩種模式。`params` 是 `ElicitRequestFormParams` 和 `ElicitRequestURLParams` 的聯集；用 `isinstance` 來分支。
* 若是 URL，把 `params.url` 顯示給使用者，回傳他們選的 action。絕不帶任何 `content`。
* 若是表單，真正的應用程式會呈現 `params.requested_schema`，並把使用者的輸入當作 `content` 回傳。這裡的回呼永遠用一個固定答案說好，正是測試裡想要的那種回呼。
* 傳入回呼同時也是**能力宣告**：伺服器就是靠這個得知這個用戶端可以被問。用戶端還能替伺服器回答的其他事情，請見**[用戶端回呼](../client/callbacks.md)**。

!!! info
    徵詢是從**伺服器**發往**用戶端**的請求，而這種請求只存在於傳統交握的工作階段（session）上，這就是這個用戶端傳入 `mode="legacy"` 的原因。在 **2026-07-28** 連線上，工具改為把問題從呼叫中**回傳**出去來問；那個流程請見**[多輪往返請求](multi-round-trip.md)**。

### 試試看 {#try-it}

用 Streamable HTTP 啟動 `ctx.elicit` 表單模式的 `server.py`（有 `book_table` 的那個；一行指令請見**[執行伺服器](../run/index.md)**），然後執行用戶端的 `main()`，向 `book_table` 訂聖誕節當天。

回呼會印出它收到的問題：

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

它回答 `{"accept_alternative": True, "date": "2025-12-27"}`，而一直在 `await ctx.elicit(...)` 裡等著的工具便完成訂位：

```text
Booked a table for 2 on 2025-12-27.
```

現在換成 URL 模式的 `server.py`，讓同一個 `main()` 改呼叫 `pay_deposit`：同一個回呼會走另一個分支，印出付款連結，工具則回傳「Complete the payment in your browser.」。呼叫途中的一次往返，雙向都走過了。

!!! check
    現在把 `elicitation_callback=` 從 `Client` 拿掉，再向 `book_table` 訂一次聖誕節當天。整個呼叫會以協定錯誤失敗：

    ```text
    Elicitation not supported
    ```

    沒有註冊回呼的用戶端從來沒有宣告 `elicitation` 能力，所以沒有人可以問。你的工具拿到的不是 `"decline"`，而是例外。設計時要考慮到這點：每一個徵詢都需要對「如果沒辦法問怎麼辦？」有個合理的答案。

## 重點回顧 {#recap}

* 標註為 `Annotated[T, Resolve(fn)]` 的參數由解析器填入，解析器必須問的時候就回傳 `Elicit(...)`。在每一種連線上都能用。
* schema 是一個扁平的 Pydantic 模型：只能有基本型別欄位，回來的路上會驗證。
* `result.action` 是 `"accept"`、`"decline"` 或 `"cancel"`；`result.data` 只在 accept 時存在。
* `await ctx.elicit(message, schema=Model)` 從工具本體內部問，`await ctx.elicit_url(message, url, elicitation_id)` 則用於所有絕對不能經過模型的東西（`ctx.session.send_elicit_complete(elicitation_id)` 表示頻外的部分完成了）。兩者都是伺服器對用戶端的請求：需要用戶端在舊版連線上。
* 用戶端用一個 `elicitation_callback` 回答，依 params 的型別分支；註冊它就是宣告能力。
* 在 2026-07-28 連線上，伺服器是回傳問題而不是推送問題；同一個回呼改由**[多輪往返請求](multi-round-trip.md)**餵入。

那個回傳底下的一切（重試迴圈、保護 `requestState`、自己驅動它）請見**[多輪往返請求](multi-round-trip.md)**。
