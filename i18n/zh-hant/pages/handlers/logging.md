---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# 記錄 {#logging}

在工具裡寫記錄的方式，和在其他任何 Python 函式裡一樣：用標準函式庫。

MCP 有一個協定層級的 **logging 能力**：伺服器可以透過 `Context` 物件上的方法，把記錄訊息以通知的形式推送給用戶端。規格的 2026-07-28 修訂版**將這個能力標為已棄用，而且沒有提供替代方案**，所以這份說明文件不教它。哪些東西已棄用、該改用什麼，完整清單請見 **[已棄用的功能](../deprecated.md)**。

該改用的做法，就是在其他任何 Python 程式裡會用的做法：標準函式庫。

## 會寫記錄的工具 {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` 會給你一個以模組名稱命名的 logger。在檔案最上方建立一次就好。
* 在工具裡呼叫 `logger.info(...)`，就跟在其他任何函式裡一樣。不用注入什麼、不用 `await` 什麼，也沒有任何 MCP 專屬的東西。

!!! check
    呼叫這個工具，看看完整的結果：

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    記錄那一行完全不在裡面。記錄是寫給**你**看的，也就是負責維運伺服器的人。模型永遠看不到它。如果有東西該讓模型讀到，就 `return` 它。

## 記錄去了哪裡 {#where-it-goes}

對 **stdio** 伺服器來說，這個問題比平常更重要。主機把你的伺服器當成子處理程序啟動，並從它的 **stdout** 讀取 MCP 訊息。標準錯誤是你的。

標準函式庫本來就做對了：記錄輸出預設寫到 `sys.stderr`。你的 `logger.info(...)` 那些行會出現在終端機（或主機收集子處理程序 stderr 的地方），協定串流則保持乾淨。

!!! tip
    不要在 stdio 伺服器裡用 `print()`。`print` 寫到 **stdout**，而 stdout 屬於協定。服務期間，SDK 會把實際**被 flush** 的 stdout 輸出轉向 stderr，所以它不會弄壞線路；但在區塊緩衝的處理程序裡，`print()` 的內容通常會一直留在 `sys.stdout` 的緩衝區裡沒被 flush，直到直譯器在結束時把它排空，直接倒進協定串流。就算被轉向了，那一行也是原封不動地混在記錄輸出之中，沒有層級、沒有 logger 名稱，也沒辦法過濾。

    `logger.debug("got here")` 一樣只是一行的功夫，而且會去到對的地方。

## 層級 {#the-level}

不需要自己呼叫 `logging.basicConfig()`。建立 `MCPServer` 時就已經呼叫過了：它裝上一個指向標準錯誤的 handler，層級就是你以 `log_level=` 傳入的值，所以只要 `MCPServer("Bookshop", log_level="DEBUG")` 就能看到 `logger.debug(...)` 那些行。

預設值是 `"INFO"`。

`logging.basicConfig()` 永遠不會取代已經存在的 handler。如果在建立伺服器之前就自己設定好記錄，以你的設定為準。

## 試試看 {#try-it}

用 MCP Inspector 執行伺服器：

```console
uv run mcp dev server.py
```

從 **Tools** 分頁呼叫 `search_books`。Inspector 會顯示結果：只有回傳值。至於這一行

```text
Searching for 'dune'
```

則去了標準錯誤：終端機，而不是線路。

!!! info
    如果你真正想要的是**追蹤**（每個請求、花了多久、有沒有失敗），那你要的不是記錄行，而是 span。你的伺服器已經在送出它們了：SDK 預設就用 OpenTelemetry 追蹤每一則訊息。請見 **[OpenTelemetry](../run/opentelemetry.md)**。

## 重點回顧 {#recap}

* MCP 協定的 logging 能力已被 2026-07-28 規格棄用，且沒有替代方案。不要以它為基礎開發。
* 模組層級寫 `logger = logging.getLogger(__name__)`，工具裡寫 `logger.info(...)`。整個模式就這樣。
* 記錄輸出永遠到不了模型。只有 `return` 的值會。
* 標準錯誤是你的；stdout 屬於協定。服務期間，SDK 會把被 flush 的零星 stdout 輸出轉向 stderr，但沒被 flush 的 `print()` 仍可能在結束時排空到線路上，而被轉向的行送達時也沒有任何標示；改用 `logging`，它的 handler 每一筆記錄都會 flush。
* `MCPServer(..., log_level="DEBUG")` 設定層級，而你先做好的記錄設定不會被動到。

要告訴已連線的用戶端伺服器上有東西變了（工具清單、某個資源），請見 **[訂閱](subscriptions.md)**。
