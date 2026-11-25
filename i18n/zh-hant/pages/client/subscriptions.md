---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# 訂閱 {#subscriptions}

伺服器的目錄不是固定的。工具會在執行時出現，資源 URI 背後的內容也會改變。用戶端透過 `client.listen(...)` 得知這些變化：一個 `subscriptions/listen` 請求，它的回應**就是**串流。這條串流會一直開著，承載用戶端所要求的變更通知。

這一頁講的是用戶端這一端：開啟串流、在主流程旁邊監看它，以及處理它的結束。發布變更、篩選和提供這個方法，則是伺服器那一邊的事，寫在「在處理函式內部」底下的 **[訂閱](../handlers/subscriptions.md)**。這裡的範例對接的是在那一頁建立的衝刺看板（sprint-board）伺服器。

## 監看串流 {#watching-the-stream}

一個訂閱就是一個上下文管理器。進入它會送出請求，把你的關鍵字引數當作訂閱的篩選條件，並等待伺服器的確認，所以區塊開始時串流已經是活的了。

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

迭代會產生四種有型別的事件：`ToolsListChanged`、`PromptsListChanged`、`ResourcesListChanged` 和 `ResourceUpdated(uri=...)`。

事件只說**什麼**變了，從不說**怎麼**變的。這就是 `follow_board` 會呼叫 `read_resource` 和 `list_tools` 的原因：事件是重新擷取的信號。讀 `event.uri`，不要自己假設是哪個資源變動了：篩選條件可以列出好幾個 URI，伺服器也可能回報其中某個 URI 的子資源有變更。

等著被取用的重複事件會合併成一個，而重新擷取仍然能拿到目前的狀態。只有完全相同的事件才會合併：兩個 URI 不同的 `ResourceUpdated` 是兩個事件。

這個訂閱物件還有兩個屬性：

* `sub.honored` 是伺服器確認的篩選條件：一個 `SubscriptionFilter`，帶有你傳入的欄位，以屬性的方式讀取（`sub.honored.prompts_list_changed`）。`MCPServer` 會接受你要求的每一種，所以它會把你的請求原樣回傳。支援較少種類的伺服器確認的也較少，而且被接受的種類仍可能永遠不會觸發。伺服器也可能拒絕整個請求而不是確認它（見伺服器那一頁的[決定誰可以監看](../handlers/subscriptions.md#deciding-who-may-watch)），這會以該請求的錯誤呈現。
* `sub.subscription_id` 是 listen 請求的 id，也就是蓋在這條串流每個訊框上的那個 id。可以同時開著好幾個訂閱，各自靠自己的 id 解多工。

## 監看而不阻塞 {#watching-without-blocking}

`follow_board` 會一直執行到伺服器關閉串流為止，而這可能永遠不會發生，所以單獨執行時它會佔據你的整個程式。實際的用戶端希望監看器在主流程**旁邊**執行：代理程式呼叫工具的同時，監看器讓快取或 UI 保持最新。

先開啟訂閱，再啟動監看器，然後繼續做你的事。

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` 從第一個範例匯入 `BOARD` 和 `read_board`，這個 repo 把它存成 `tutorial003.py`。如果你把產生出來的檔案並排存成 `client.py` 和 `app.py`，就改寫成 `from client import BOARD, read_board`。更下面的 `watch.py` 範例也用同樣的方式匯入 `read_board`。

重點在於順序。沒有任何東西會重播，所以在你的串流存在之前發布的事件就錯過了。進入 `client.listen(...)` 會等待確認，所以從那一刻起的每個變更都會送到監看器，而你在區塊內取得的快照不會漏掉任何一個。

串流開著的時候，請求可以自由地在旁邊執行，不管來自監看器任務還是其他任務，都在同一個用戶端上。因為**重複**的未取用事件會合併，忙碌的主流程可能只產生一次重新擷取，而不是三次。不同的事件不會合併：列出許多 URI 的篩選條件會為每個 URI 各排一個待處理事件。

要停止監看，離開區塊就好：沒有 `unsubscribe` 呼叫。取消擁有該區塊的任務就會幫你做到這件事，SDK 會依傳輸方式預期的方法取消 listen 請求：在 Streamable HTTP 上，就是關閉該請求的串流。在應用程式整個存活期間執行的監看器永遠不會自己結束，所以在關閉時取消它，或取消它所屬任務群組的範圍。

## 串流會結束 {#streams-end}

串流的結束方式有兩種，兩種都是一般的控制流程。伺服器優雅地關閉會結束 `async for`；突然中斷則會引發 `SubscriptionLost`。

兩者的差別在於診斷，而不在於接下來該做什麼：串流沒了，沒有任何東西會重播，還在意的監看器就重新 listen 並重新擷取。

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

伺服器會因為自己的理由優雅地關閉串流，包括甩掉積壓太多的訂閱者，所以乾淨的結束並不是該停止監看的信號。重新 listen 之前先退避一下。

`SubscriptionLost` 也有一個本地端的成因。用戶端最多保留 1024 個未取用的事件，落後到這種程度的取用端會失去訂閱，而不是無限制地膨脹。讓 `async for` 的本體保持簡短，慢的工作放到別處做。

`keep_following` 只攔截 `SubscriptionLost`。進入 `listen()` 也可能引發 `MCPError`（連線失敗，或伺服器不提供這個方法）、`TimeoutError`（沒有收到確認）和 `ListenNotSupportedError`（2026 之前的連線）。決定其中哪些是監看器該重試的：最後一種永遠不會自己好。

## 重點回顧 {#recap}

* 進入 `async with client.listen(...)`；進入時會等待確認，所以之後發布的東西都不會漏掉。
* 用 `async for event in sub` 迭代。事件是重新擷取的信號，從來不是承載內容。
* 先開啟訂閱，再把監看器當成任務執行，工具呼叫就能在旁邊持續進行。
* 乾淨的結束會讓迴圈停下；中斷則引發 `SubscriptionLost`。不管哪一種：重新 listen、重新擷取，但先退避。
* 離開區塊就是取消訂閱。

發布這些事件、縮小篩選條件，以及擴展到超過一個處理程序，是伺服器那一邊的事：**[訂閱](../handlers/subscriptions.md)**。同樣這些事件也能讓用戶端快取保持正確，而 **[快取](caching.md)** 就是下一頁。
