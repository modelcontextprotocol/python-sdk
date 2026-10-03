---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# 相依性 {#dependencies}

工具的引數來自模型。但有些值根本不該由模型提供：從自己的紀錄查出來的價格、只有真人能給的確認，以及任何模型一旦憑空捏造就可能出錯的東西。

**相依性**是由你自己的函式填入的參數。在參數上加註記、指名函式，SDK 就會在工具執行前呼叫它。

## 宣告一個 {#declare-one}

把參數的型別包進 `Annotated[...]`，再加上 `Resolve(fn)`：

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` 是一個**解析器**：一個普通函式，SDK 會在 `reserve_book` 之前執行它，回傳值就成為 `stock` 引數。
* 它的 `title` 參數就是工具本身的 `title` 引數，**依名稱**比對。解析器看到的值，和工具本體將看到的驗證後的值完全相同。
* 工具本體一開始就拿到一個現成的 `Stock`。工具裡沒有查詢程式碼，也沒有「萬一找不到怎麼辦」的開場白。

!!! info
    如果用過 FastAPI，這就是 `Depends`。同樣的做法，同樣的理由：函式宣告自己需要什麼，框架負責供應，接線全寫在型別註記裡。

### 模型看不到 {#invisible-to-the-model}

這是 `tools/list` 為 `reserve_book` 回報的輸入 schema：

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

只有一個屬性。和 **[Context](context.md)** 裡的 `Context` 一樣，解析出來的參數是你和 SDK 之間的約定：`stock` 不在 schema 裡，模型從頭到尾不知道它的存在，用戶端就算硬是送來 `stock` 值也會被忽略。解析器的值是工具唯一可能收到的值。

最後這點正是重點。模型無法提供的參數，就是模型無法弄錯的參數。

### 試試看 {#try-it}

用 MCP Inspector 執行伺服器：

```console
uv run mcp dev server.py
```

`reserve_book` 的表單只有一個 `title` 欄位，完全沒有 `stock`。用 `Dune` 呼叫它：

```text
Reserved 'Dune' (6 copies left).
```

工具本體什麼都沒查：`check_stock` 先執行，它回傳的 `Stock` 以引數的形式送了進來。試試 `Neuromancer`，同一個解析器會交給工具一個零。

!!! tip
    其實可以直接在工具本體裡呼叫 `check_stock(title)`。當這個值值得比一個輔助函式呼叫更鄭重的對待時，再把它宣告成相依性：每個需要庫存的工具都宣告同一個參數，而且不管有多少個工具宣告它，SDK 每次呼叫最多只執行解析器一次。接下來幾節補上其餘部分：彼此相依的解析器，以及會詢問使用者的解析器。

## 相依性的相依性 {#dependencies-of-dependencies}

解析器可以用同樣的註記宣告自己的相依性：

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` 相依於 `check_stock`。SDK 依序執行這張圖：先是庫存，再來是預估，最後是工具。
* `stock` 和 `delivery` 最終都需要 `check_stock`，但它**每次呼叫只執行一次**。一次庫存查詢，兩個取用端。
* 不需要註冊任何東西。這張圖**就是**那些註記。

!!! check
    別光憑信任就接受「每次呼叫一次」。在 `check_stock` 裡放一個 `print`，再從 Inspector 呼叫 `order_book`：每次呼叫印出一行。兩個取用端，一次查詢。

SDK 在工具註冊時分析這張圖，而不是在呼叫時。無法歸類的參數（不是 `Context`、不是 `Resolve(...)`、也不是工具引數的名稱）以及解析器之間的循環，都會在啟動時引發 `InvalidSignature`。伺服器在任何用戶端連上之前就會失敗，錯誤訊息裡會指出出問題的參數或解析器。

解析器的參數解析方式和工具的完全一樣：另一個 `Resolve(...)`、依名稱對應的工具引數，或是 `Context`：`ctx.headers`、生命週期物件，全部都拿得到。

!!! warning
    在 HTTP 傳輸上，`Context` 包含 `ctx.headers`。標頭和任何工具引數一樣，是**用戶端提供的輸入**：拿來放語系或功能旗標沒問題，但絕不能當作身分。呼叫端是誰，要由授權層（**[授權](../run/authorization.md)**）決定，而不是任何人都能設定的標頭。

!!! tip
    「每次呼叫一次」就是字面上的意思：下一次 `tools/call` 會再執行一次 `check_stock`。應該活得比單一請求久的資源（資料庫連線池、HTTP 用戶端）屬於 **[生命週期](lifespan.md)** 的範疇，解析器可以透過 `ctx.request_context.lifespan_context` 取得它。

## 非問不可時才問 {#ask-when-you-must}

解析器不一定要知道答案。它可以回傳 `Elicit(message, Model)`，SDK 就會去問使用者，動用的是 **[徵詢（elicitation）](elicitation.md)** 機制，替你代勞：

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* 有庫存：`confirm_backorder` 直接回傳一個 `Backorder`。**不提問，不往返。**只有在使用者的答案有影響時才會打擾他們。
* 沒庫存：SDK 送出徵詢，依 `Backorder` 驗證答案，再注入進來。解析器完全不碰協定。
* 工具像讀其他引數一樣讀取 `backorder.confirm`。回答**不要**也算是一種回答：徵詢以 `confirm=False` 被接受，工具照樣執行，只是不下訂單。提問變成了前置條件，而不是塞在工具本體裡的管線程式碼。

那如果使用者根本不回答，拒絕了這個問題或是取消它呢？

!!! check
    對 `Neuromancer` 執行 `order_book`，然後拒絕這個問題。註記寫成 `Annotated[Backorder, Resolve(...)]` 時，工具本體根本不會執行；呼叫會失敗，回傳模型讀得懂的錯誤結果：

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

對前置條件來說，這是正確的預設行為：沒有答案，就沒有訂單。如果拒絕是工具想自己處理的結果（跳過缺貨預訂，但仍然推薦另一本書），就改註記成 `ElicitationResult[Backorder]`，工具會收到完整的接受／拒絕／取消結果，可以據此分支。**[徵詢](elicitation.md)** 示範了那種寫法，以及關於提問的其他一切：schema 規則、三種回答、對話中用戶端那一側。

!!! info
    框架依協商出的協定版本決定問題走哪種傳輸；上面的程式碼在兩種情況下完全相同。在 **2026-07-28** 及之後，問題搭在一個多輪往返（multi-round-trip）的 `tools/call` 裡：伺服器回傳問題，用戶端的 `elicitation_callback` 回答它，`Client` 替你重試這次呼叫（**[多輪往返請求](multi-round-trip.md)**）。在 **2025-11-25** 及更早，則是呼叫途中的一個同步徵詢請求。每個問題在每次呼叫中恰好問一次，這是對問題的保證，不是對解析器的保證。在多輪往返的形式下，每當呼叫在提問後恢復，任何解析器都可能再執行一次，所以 `return Elicit(...)` 之前的程式碼在每一輪都會執行；已記錄的答案接著會滿足重複出現的問題，不會再次詢問使用者。已記錄的答案只在解析器提問時才會被查閱；像 `check_stock` 這樣**不**提問就給出答案的解析器，永遠提供自己計算出的值。因為每個答案都要對回它的問題，會徵詢的解析器必須從工具的引數和先前的答案確定性地推導出它的問題。每次呼叫才產生的值（`default_factory` 產生的 id、時間戳記）在每一輪都會重新推導，不能出現在答案要綁定的問題裡。用這種易變資料組出的問題會讓每個已記錄的答案看起來都過期，於是伺服器每一輪都重問一次，直到用戶端的輪數上限結束這次呼叫。

## 問用戶端，不是問使用者 {#ask-the-client-not-the-user}

徵詢是解析器能問的三種問題之一，而多輪往返流程不允許其他種類。另外兩種是問**用戶端**而不是使用者：回傳 `Sample(...)` 透過用戶端執行一次 LLM 呼叫（一個 `sampling/createMessage` 請求），或回傳 `ListRoots()` 取得用戶端目前的根目錄（roots）。兩者都沒有接受／拒絕的結果；取用端直接註記結果型別，`CreateMessageResult`（請求帶有 `tools` 或 `tool_choice` 時是 `CreateMessageResultWithTools`）或 `ListRootsResult`：

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* 框架替它們安排路徑的方式和 `Elicit` 完全一樣：在 **2026-07-28** 上走多輪往返的 `tools/call` 內部，在 **2025-11-25** 上走獨立的伺服器→用戶端請求。未宣告的能力會以 `-32021` 協定錯誤拒絕這次呼叫（`sampling`、`roots`、表單模式的 `elicitation`；請求帶有 `tools` 或 `tool_choice` 時是 `sampling.tools`）。
* 上面資訊框裡關於問題的一切原封不動地適用：`Sample` 請求是以它精確的呈現內容對應到已記錄的結果，所以要從工具的引數和先前的答案確定性地建構它；這樣用戶端每次工具呼叫只付一次 LLM 呼叫的代價，而不是每一輪一次。已記錄的結果在這次呼叫剩餘的過程中都搭在 `request_state` 上，所以非常大的生成結果會讓剩下的每次往返都變得更重。
* 獨立的取樣（sampling）和根目錄**功能**在 2026-07-28 已棄用（SEP-2577）。需要用戶端模型的新伺服器透過這個載體來問；不需要的伺服器應該直接整合 LLM 供應商。`"none"` 以外的 `include_context` 值本身也已棄用；避免使用。

## 重點回顧 {#recap}

* 在工具參數上寫 `Annotated[T, Resolve(fn)]`：SDK 執行 `fn` 並注入它的回傳值。
* 解析出來的參數模型看不到，用戶端也無法提供。模型不該自己捏造的值（價格、身分、權限）就屬於這裡。
* 解析器的參數用同樣的方式解析：`Context`、另一個 `Resolve(...)`，或依名稱對應的工具引數。不管有多少取用端，這張圖每一輪最多執行每個解析器一次；每個問題恰好問一次，而呼叫在提問後恢復時，任何解析器都可能再執行一次。
* 有問題的圖在註冊時就以 `InvalidSignature` 失敗，而不是呼叫到一半才出錯。
* 回傳 `Elicit(message, Model)` 來詢問使用者，而且只在非問不可時才問。未包裝的註記遇到拒絕會中止；`ElicitationResult[T]` 讓工具可以分支。
* 回傳 `Sample(...)` 或 `ListRoots()` 向用戶端要一個 LLM 生成結果或根目錄清單；注入的是單純的結果。

伺服器在啟動時建立一次的狀態，以及處理函式如何取得它，請見 **[生命週期](lifespan.md)** 頁面。
