---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# 訂閱 {#subscriptions}

伺服器的目錄不是固定的。工具會在執行時出現，資源 URI 背後的內容也會改變。

**訂閱**是用戶端得知這些變化的方式。用戶端送出一個 `subscriptions/listen` 請求，而這個請求的回應**就是**串流：它會保持開啟，並傳送用戶端要求的變更通知。

## 從工具發布 {#publish-it-from-the-tool}

你這邊要做的只有一行：發布變更。

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` 會送達每一個訂閱了該 URI 的開啟串流，其他人都不會收到。
* `await ctx.notify_tools_changed()` 會送達每一個要求工具清單變更的串流。收到它的用戶端會再次呼叫 `tools/list`，這時就看得到 `sprint_report`。
* 同系列的還有 `notify_prompts_changed()` 和 `notify_resources_changed()`。
* 沒有訂閱者，就沒有工作。對閒置的伺服器發布是空操作，所以永遠不必檢查有沒有人在聽，只要說明什麼變了。

`MCPServer` 會替你服務 `subscriptions/listen`。線路上的義務（第一個訊框是確認、逐串流過濾、每個訊框都帶訂閱 id）是 SDK 的工作。

!!! check
    在線路上，一個過濾條件指名 `board://sprint` 的串流，在 `complete_task` 執行之後看起來像這樣：

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    注意更新**沒有**帶什麼：看板本身。每個訊框都在 `_meta` 底下帶著 listen 請求的 JSON-RPC id，而那個 id 就是訂閱 id。它由用戶端產生：Python 的 `Client` 使用像 `"listen-1"` 這樣的字串；其他用戶端可能使用整數。

## 只給要求的內容 {#only-what-was-asked-for}

過濾條件是一份契約。一個要求了工具清單變更和一個資源 URI 的串流，只會收到這兩種，別的都不會。發布一個提示詞變更，那個串流會保持安靜。

`MCPServer` 以完全相同的字串比對資源 URI，所以指名 `board://sprint` 的串流完全不會收到 `board://sprint/tasks/1` 的任何動靜。規格允許伺服器回報已訂閱 URI 的子資源變更；`MCPServer` 從不這麼做，但用戶端的設計會預期這種情況。

串流**不是**的兩件事：

* **它不是重播記錄。** 斷掉的串流就沒了，沒人連線時發布的事件也不會排入佇列。用戶端會重新 listen 並重新擷取。
* **它不是 2025 的路徑。** 呼叫了 `resources/subscribe` 的用戶端由 `ctx.session.send_resource_updated(uri)` 服務。`notify_*` 方法只會送達 `subscriptions/listen` 串流。

## 決定誰可以觀看 {#deciding-who-may-watch}

預設情況下，每一種要求的類型和 URI 都會被接受：任何呼叫端都可以觀看你發布的任何 URI。沒有任何東西會去問你的讀取處理函式，因為沒有人在讀取。一個會被 `files://{name}` 處理函式拒絕的呼叫端，仍然可以對 `files://payroll.csv` 開啟串流，得知它變了、什麼時候變的。它永遠不會得知內容，也無法探測有哪些東西存在，因為未知的 URI 一樣會被接受，只是永遠不會觸發。範圍很窄但確實存在，所以在從多租戶伺服器發布每位使用者各自的 URI 之前，先加上把關。

把關用的是中介軟體。它會在 SDK 確認之前看到 `subscriptions/listen` 請求，並在呼叫端要求任何他們無權讀取的東西時拒絕：

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` 是原始請求，所以中介軟體自己把它驗證成 `SubscriptionsListenRequestParams`，再讀出用戶端要求的過濾條件。
* 拒絕的方式是在 `call_next(ctx)` 之前引發 `MCPError`：用戶端會收到那個錯誤而沒有串流，連線則繼續。訊息要保持一致、不指名任何 URI，這樣拒絕就永遠不會證實哪些 URI 受到保護。
* 一個 `can_access(user, uri)` 回答兩個問題。資源處理函式在 `resources/read` 時問它；中介軟體在 `subscriptions/listen` 時問它。把那張表換成資料庫或你的 RBAC 系統，兩邊依然同步。
* 這個決定在串流的整個存續期間都有效。沒有逐事件的重新檢查，所以如果呼叫端的存取權可能在串流中途失效（權杖過期），就在失效時結束那個呼叫端的連線。

完整的中介軟體契約，包括它還包裝了什麼、以及為什麼標示為暫定，請見 **[中介軟體](../advanced/middleware.md)**。

## 用戶端那一端 {#the-client-end}

以下是串流另一端的用戶端，正在追蹤看板：

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

進入 `client.listen(...)` 會送出請求並等待你的確認，所以區塊開始時串流已經接通，而每個有型別的事件都是重新擷取的訊號，從來不是酬載。整份契約一個畫面就講完了。用戶端那一端的其他一切都在它自己的頁面上：在主流程旁邊觀看、串流的結束，以及重新 listen。請見「用戶端」章節下的 **[訂閱](../client/subscriptions.md)**。

## 擴展到單一處理程序之外 {#scaling-past-one-process}

發布的內容透過 `SubscriptionBus` 從處理函式送到開啟中的串流。預設是記憶體內的：一個處理程序，所有串流都在裡面。在你於負載平衡器後面執行多個副本之前，這都是正確答案；因為到那時，用戶端的串流會固定在某一個副本上，而另一個副本上的發布必須送得到它。

那個接縫由你實作：在你的 pub/sub 後端上實作兩個方法。

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` 是你的，每個副本上負責解碼送達的訊息並呼叫每個已註冊監聽器的讀取任務也是你的。監聽器是同步的，不可以引發例外，並且在伺服器的事件迴圈上執行。

匯流排承載的是有型別的 `ServerEvent` 值（四個小小的 dataclass），從來不是 JSON-RPC。加註、過濾和串流生命週期都留在 SDK 裡，所以匯流排的實作不可能破壞協定，只能在處理程序之間搬運事件。

要從請求之外發布，就自己建構匯流排，這樣你才握有參考。什麼都不傳時 `MCPServer` 會在內部建立一個，而且不會公開它。

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## 低階組合方式 {#the-low-level-composition}

在低階的 `Server` 上沒有任何預先接好的東西，同樣的零件三行就能組起來：

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* 匯流排是你的，所以直接對它發布：`await bus.publish(ResourceUpdated(uri=...))`。把它放在處理函式搆得到的地方：這裡是模組範圍，較大的應用程式則放在生命週期裡。
* `ListenHandler(bus)` 就是 `MCPServer` 註冊的同一個處理函式，而 `on_subscriptions_listen=` 是一個普通的處理函式插槽。想要不同的語意，就把你自己的 callable 放進那個插槽，規格上的義務就轉到你身上：先確認、每個訊框加註訂閱 id、過濾條件之外的一律不送。
* `ListenHandler.close()` 會優雅地結束每一個開啟的串流。每一個都會收到 listen 請求的結果作為最後一個訊框，這是規格用來表示伺服器刻意結束訂閱的方式。它會在那些串流清空完畢之前回傳，所以在拆掉傳輸之前給它們一點時間。沒有它，串流會在用戶端斷線時結束。

## 重點回顧 {#recap}

* 用戶端用一個 `subscriptions/listen` 請求選擇加入，而回應就是串流。服務它的功能是內建的。
* 用 `ctx.notify_*` 發布，SDK 負責加註、過濾和生命週期的工作。
* 事件是訊號，不是酬載。兩端都重新擷取。
* 用戶端那一端是 `async with client.listen(...)`：完整說明請見「用戶端」章節下的 **[訂閱](../client/subscriptions.md)**。
* 在低階的 `Server` 上，同樣的零件自己組：一個匯流排、`ListenHandler(bus)`、`on_subscriptions_listen` 插槽。
* 橫向擴展代表實作 `SubscriptionBus`（兩個方法），然後以 `MCPServer(subscriptions=...)` 傳入。

執行提供這一切的伺服器，不管是一個副本還是 20 個，請見 **[部署與擴展](../run/deploy.md)**。
