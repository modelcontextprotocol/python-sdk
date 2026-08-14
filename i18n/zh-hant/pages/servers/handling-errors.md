---
translation:
  sections: [e33d441f12d50535, 7099694c603e0f5f, c1df4cf9673433e6, c9cd294541422e6e, 6cec073617bfd037, efa92b8f99e908c8, 6a22a29e27fb4601]
  tool: 1
---
# 處理錯誤 {#handling-errors}

工具失敗的方式有兩種，而 SDK 對待它們的方式截然不同。

引發一般的例外，看到的是**模型**。引發 `MCPError`，看到的是**協定**。

這一頁談的是怎麼選。

## 模型能修正的錯誤 {#an-error-the-model-can-fix}

拿一個查東西的工具來說，讓查詢落空：

```python title="server.py" hl_lines="11-12"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

這兩行跟 MCP 一點關係也沒有。`get_author` 引發的是普通的 `ValueError`，任何 Python 函式都會這麼做。

用一個不在目錄裡的書名呼叫它，看看結果：

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* 請求**成功**了。有結果；呼叫端沒有引發任何東西。
* `is_error` 是 `True`，而例外的訊息（前面加上工具名稱）就在 `content` 裡，正是模型讀取的地方。
* `structured_content` 是 `None`。失敗的呼叫沒有回傳值可以結構化。

這是**工具錯誤**，也是工具引發**任何**例外時的預設行為。而且幾乎總是你想要的。

呼叫工具的是模型，引數也是它選的。所以工具錯誤就是對話中的一個回合：模型讀到「No book titled 'Nothing' in the catalog.」，發現自己猜錯了書名，就換個更好的再呼叫一次。只寫了一個 `raise`，就得到一個會自我修正的 agent。

!!! tip
    永遠不要從工具 `return` 錯誤訊息。回傳的字串 `is_error=False`，所以在模型（以及每個用戶端 UI）看來，工具是成功的，那個字串就是答案。要用 `raise`。那個旗標才是訊號。

## 模型無法修正的錯誤 {#an-error-the-model-cannot-fix}

現在把 `ValueError` 換成 `MCPError`。

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` 是 SDK 的**協定錯誤**。它是工具包裝層唯一**不會**攔截的例外：它會往外傳播，整個 `tools/call` 請求以 JSON-RPC 錯誤失敗，而不是回傳結果。

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **沒有結果**。沒有 `content`，沒有 `is_error`：模型沒有東西可讀。
* 錯誤改由**主機（host）**應用程式收到，跟工具根本不存在時一模一樣。
* `code`、`message` 和 `data` 原封不動地送達。`INVALID_PARAMS` 是 `-32602`；`mcp.types` 把它和其他 JSON-RPC 錯誤碼（`INVALID_REQUEST`、`INTERNAL_ERROR`……）都匯出成常數，所以永遠不用手打魔術數字。

!!! check
    同樣的查詢、同樣落空，但現在呼叫在用戶端**引發**例外，而不是回傳：

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    第一個版本交給模型一句它能回應的話。這個版本什麼都沒給。對 `get_author` 來說這絕對更糟，而這正是下一節的重點。

## 該引發哪一個 {#which-one-to-raise}

兩條路徑回答的是兩個不同的問題。

* **引發任何例外**，用於**執行**上的失敗：工具想做的事沒做成。呼叫是模型選的，所以模型應該看到後果，並有機會補救。拼錯的書名、逾時的上游 API、不存在的資料列：都是工具錯誤。
* **引發 `MCPError`**，用於**請求本身**就該被拒絕的情況：用戶端缺少工具所依賴的能力、伺服器處於無法服務任何人的狀態、呼叫端跳過了必要的步驟。模型再怎麼重試也修不好這些，所以把訊息交給它毫無益處。

一個問題就能決定：**更聰明的模型能避開這個錯誤嗎？**能 -> 一般的例外。不能 -> `MCPError`。

照這個標準，第二版的 `get_author` 選錯了：換個更好的書名就能解決，所以模型理應看到訊息。放在那裡是為了示範機制，不是建議這麼做。

!!! info
    `MCPError` 位於 `from mcp import MCPError`，接受 `code`、`message` 和選用的 `data` 承載。放進去什麼，用戶端就收到什麼：SDK 會把引發的 `MCPError` 原封不動地轉送，不會加以清理。

## 不存在的資源 {#a-resource-that-doesnt-exist}

資源也畫了同一條線，並為常見情況提供了一個具名的例外。

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` 是一個**範本**。它能比對**任何**書名，所以「URI 格式正確」和「這本書存在」是兩個不同的問題，而只有你的函式能回答第二個。

回答不了的時候，引發 `ResourceNotFoundError`。SDK 會把它轉成規格指派給缺漏資源的協定錯誤：`-32602`，並把請求的 URI 放在 `data` 裡，讓用戶端知道是**哪一次**讀取失敗。

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

注意這裡沒有 `is_error=True` 那種半成品結果。資源讀取要嘛回傳內容，要嘛失敗：資源只有協定這條路。範本以及資源的其他一切都在 **[資源](resources.md)**。

## 永遠不用引發的錯誤 {#errors-you-never-raise}

錯誤的引數永遠到不了你的函式。

傳給 `get_author` 一個不是字串的 `title`，SDK 會在呼叫你**之前**就依輸入 schema 拒絕它，同樣是模型能讀懂並修正的那種 `is_error=True` 工具錯誤。**[工具](tools.md)** 用 `Field(le=50)` 限制示範了同樣的拒絕。

這表示有一整類 `raise` 陳述式不用寫：不要重新驗證自己的型別提示。

!!! info
    這一頁的一切都是**用戶端**看到的東西，而寫測試用的記憶體內 `Client` 看到的完全一樣。就算是 `raise_exceptions=True` 也不會把工具錯誤變回 traceback：等到那個旗標能起作用時，你的例外早已是 `is_error=True` 的結果。對結果做斷言。**[測試](../get-started/testing.md)** 說明了這個模式。

## 重點回顧 {#recap}

* 在工具裡引發**任何例外** -> 呼叫回傳 `is_error=True`，訊息在 `content` 裡。模型讀到後可以重試。這是預設行為。
* 引發 **`MCPError`** -> 呼叫本身以 JSON-RPC 錯誤失敗。模型什麼都看不到；由主機處理。`code`、`message` 和 `data` 完整保留。
* 決定性的問題：「更聰明的模型能避開這個錯誤嗎？」能 -> 例外。不能 -> `MCPError`。
* 資源處理函式引發的 `ResourceNotFoundError` -> 協定的 `-32602`，URI 在 `data` 裡。
* 錯誤的引數會在函式執行前依 schema 被拒絕；這些不用 `raise`。
* `from mcp import MCPError`；錯誤碼常數來自 `mcp.types`。

錯誤處理完畢。這就是伺服器**公開**的全部內容。每個處理函式在執行時能讀到什麼、又能反過來對用戶端做什麼，是下一節的主題：**[在處理函式內部](../handlers/index.md)**。

最常碰到的 SDK 錯誤的確切文字、各自的意思，以及每一個的一步修正法，都在 **[疑難排解](../troubleshooting.md)**。
