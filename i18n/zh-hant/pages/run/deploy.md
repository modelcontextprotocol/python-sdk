---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# 部署與擴展 {#deploy-scale}

伺服器可以運作了。現在它需要一個真正的主機名稱，後面還要有不只一個 worker。

這些事幾乎都不歸 MCP 管。ASGI 伺服器、處理程序管理器、負載平衡器都由你自備。這一頁只列出少數**確實**歸 MCP 管的事：一個擋在每次部署前面的設定，以及「不只一個 worker」會改變 SDK 行為的兩個地方。

## 先做這件事：Host 允許清單 {#before-anything-else-the-host-allowlist}

`streamable_http_app()` 無從得知自己會掛在哪個主機名稱後面提供服務，所以它假設最安全的答案：localhost。沒有傳入 `transport_security=` 時，應用程式會啟用 **DNS 重新綁定防護**，只接受 `Host` 標頭為 `127.0.0.1:<port>`、`localhost:<port>` 或 `[::1]:<port>` 的請求。若有 `Origin` 標頭，它必須是同一位址的 `http://` 形式。在你自己的機器上這完全正確：它能阻止惡意網頁透過重新綁定到 `127.0.0.1` 的 DNS 名稱來操控本機伺服器。

部署到真正的主機名稱後面時，同樣的預設值會拒絕**每一個請求**，直到你另行指定。這項檢查在任何 MCP 相關的東西執行之前就先跑完，所以你寫的東西根本不會被問到：

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

`transport_security=` 就是解法。把實際提供服務的名稱加進允許清單：

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* `allowed_hosts` 的項目是精確比對的字串：`"mcp.example.com"` 比對不帶連接埠的 `Host` 標頭，`"mcp.example.com:*"` 比對任何連接埠。兩個都列上。
* `allowed_origins` 只對瀏覽器有意義，因為其他東西都不會送 `Origin`。它是 **[加入現有應用程式](asgi.md)** 裡 CORS 設定在伺服器端的對應。
* 在已經掌控 `Host` 標頭的反向代理後面，把檢查關掉才是誠實的設定：`TransportSecuritySettings(enable_dns_rebinding_protection=False)`。
* 傳入非 localhost 的 `host=`（例如 `host="mcp.example.com"`）**不會**把那個主機名稱加入允許清單。它只是讓 localhost 預設值不再啟動防護，結果是每個 Host 和 Origin 都照單全收。想表達什麼，就用 `transport_security=` 明說。

!!! check
    刪掉 `transport_security=security` 引數，照樣部署應用程式。它會啟動，`/mcp` 路由正常，而每個請求（包括單純的 `curl`）都會得到：

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    在用戶端找不到這幾個字。`421` 是純文字的 HTTP 回應，不是 JSON-RPC 錯誤，所以 MCP 用戶端只會引發一個籠統的傳輸錯誤；它不喜歡的主機名稱只會出現在**伺服器**的記錄裡，就一則警告。剛部署好卻拒絕所有連線的伺服器，在證明是別的原因之前，就是 Host 允許清單的問題。**[疑難排解](../troubleshooting.md)** 也從這裡開始。

## Worker，以及誰需要黏性 {#workers-and-who-has-to-be-sticky}

主機名稱能回應之後，就在後面放不只一個 worker。SDK 沒有這方面的設定；擴展 Starlette 應用程式的方式跟擴展任何 ASGI 應用程式一樣，把物件交給懂得 fork 的東西：

```console
uvicorn server:app --workers 4
```

四個處理程序，一個 socket。接著是每次部署都得回答的問題：**請求是否必須送到看過上一個請求的那個 worker？**

對使用 **2026-07-28** 協定的用戶端來說，不用。現代請求是一個自成一體的 POST：前面沒有 `initialize` 交握，回應上沒有 `Mcp-Session-Id`，第二個請求沒有什麼可以「回去找」的對象。送到任何一個 worker 都行。

這不是一個要你開啟的模式。`stateless_http=True` 看起來像是，但傳輸層依 `MCP-Protocol-Version` 請求標頭分流，把現代請求交給現代處理函式，然後就**回傳**了。讀取 `stateless_http` 的那一行在那個 return **之後**。並不是這個旗標在 2026-07-28 路徑上被忽略，而是根本執行不到。`stateless_http` 只是**舊版**那一支的開關，現代路徑在設計上就沒有工作階段（session）。

對規格版本 2025-11-25 或更早的舊版用戶端，答案取決於那個旗標：

| 用戶端的協定版本 | 工作階段 | 負載平衡器必須做的事 |
| --- | --- | --- |
| **2026-07-28** | 無。永遠不會設定 `Mcp-Session-Id`。 | 不用做什麼。任何 worker 都能服務任何請求。 |
| **2025-11-25 及更早**（預設） | `Mcp-Session-Id`，保存在某一個 worker 的記憶體內。 | **黏性工作階段。**後續請求若送到不同的 worker，會得到 `404`「Session not found」。 |
| **2025-11-25 及更早**，搭配 `stateless_http=True` | 無。 | 不用做什麼。代價是伺服器到用戶端的反向通道（back-channel），也就是取樣（sampling）、推送式徵詢（elicitation）、`roots/list`，以及可續傳能力。 |

黏性工作階段和舊版那一支的代價自有專頁：**[服務舊版用戶端](legacy-clients.md)**；兩個世代本身則見 **[協定版本](../protocol-versions.md)**。這裡重要的是答案的樣子：**在 2026-07-28 上你本來就是無狀態的，沒有任何東西要設定。**

本頁剩下的內容，是無狀態**沒有**幫你解決的兩件事。

## 跨 worker 的 `requestState` {#requeststate-across-workers}

**[多輪往返（multi-round-trip）](../handlers/multi-round-trip.md)** 工具需要某樣用戶端得去取得的東西（一個確認、一個選擇、一個憑證），所以它回傳的是問題而不是答案，並在重試時完成。兩輪之間，用戶端持有一個伺服器鑄造的不透明 `request_state` 權杖。重試時，伺服器得再把那個權杖打開。

「用哪一把金鑰封裝的？」預設是伺服器在建構時用 `os.urandom(32)` 產生的那一把。在 `--workers 4` 之下，那是四次建構、四個處理程序：四把不同的金鑰，從沒寫到任何地方、從不共用，重新啟動就消失。

下面是一個先問再做的工具，放在一台什麼都沒設定的伺服器上：

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

第一輪送到 worker A。Worker A 用**它自己的**金鑰封裝 `refund:120` 並回傳權杖。用戶端把問題呈現給某個人，得到同意，然後重試。這次重試是一個全新的 HTTP 請求。

!!! check
    讓那次重試送到 worker B。B 試著解封一個不是它鑄造的權杖，辦不到，於是拒絕整輪。`refund` 根本沒被呼叫；用戶端收到一個 JSON-RPC 錯誤：

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    那則訊息是**固定不變**的。過期、被竄改、拿不同的引數重播，或者（在真實部署裡遠遠最常見的原因）由兄弟 worker 封裝：用戶端每次被告知的都是同一句話，所以線路上永遠看不出是哪一項檢查失敗。真正的原因是伺服器記錄裡的一則 `WARNING`：

    ```text
    requestState rejected on tools/call: unknown key
    ```

    一個 worker 時正常、兩個 worker 時開始**偶爾**失敗的多輪往返工具，就是這個問題。兩輪仍然必須送到同一個處理程序，所以負載平衡器把它們拆開的頻率有多高，它失敗的頻率就有多高。

兩輪是兩個獨立的 HTTP 請求，好幾種再平常不過的情況都會把它們拆開：逐請求平衡的代理、中間斷掉的連線、一次部署或重新啟動、把 `request_state` 存下來並從完全不同的處理程序恢復的用戶端（**[自己驅動迴圈](../handlers/multi-round-trip.md#driving-the-loop-yourself)**）。任何一種都算「不同的 worker」。

解法是一個引數。它有**兩**半。

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** 是大家都找得到的那一半。給每個執行個體同一個祕密（至少 32 個位元組），每個執行個體就能解封任何兄弟鑄造的東西。`keys[0]` 負責封裝，清單裡每把金鑰都能解封，這就是輪替環；**[輪替金鑰](../handlers/multi-round-trip.md#rotating-keys)** 說明如何不停機地轉動它。
* **伺服器的名稱**是幾乎沒人找得到的那一半，也是共用金鑰之後跨執行個體重試仍然失敗的原因。每個封裝的權杖都帶著伺服器的 `name` 作為 **audience 宣告**，回來時嚴格檢查。用同一份程式碼建出的兩個執行個體名稱相同，永遠不會察覺這件事。替它們取不同的名字（`MCPServer(f"billing-{POD}")` 看起來像是良好的可觀測性習慣），每次跨執行個體重試就會像上面那樣被拒絕，不管有沒有共用金鑰。記錄裡寫的是 `audience` 而不是 `unknown key`；用戶端分不出差別。

祕密只鑄造一次，把同一個值交給每個執行個體。如果傳入少於 32 個位元組，SDK 自己的錯誤訊息就會叫你執行這條指令：

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "相同的金鑰，**還有**相同的名稱"
    多執行個體部署必須兩者都共用。如果各執行個體的名稱對你來說不可或缺，就改給整個機群一個明確的 audience：`RequestStateSecurity(keys=[...], audience="billing")`。這樣每個執行個體不管叫什麼，都用 `"billing"` 鑄造和接受。

封裝的其他一切都在 **[保護 `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**：它綁定什麼、每輪的 `ttl`（預設 600 秒）、自備編解碼器、為什麼未設定的預設值在 `stdio` 上完全正確。本頁的全部貢獻就是一張兩項的檢查清單：**相同的金鑰，相同的名稱。**

!!! info
    就算從沒打過 `InputRequiredResult`，你也在這條路徑上。參數用了 `Resolve(...)`（**[相依性](../handlers/dependencies.md)**）的工具就是多輪往返工具，SDK 會替它鑄造並封裝 `request_state`。同樣的預設金鑰，跨 worker 同樣的失敗，同樣的解法。

## 跨副本的變更通知 {#change-notifications-across-replicas}

用戶端的 `subscriptions/listen` 串流是一個長時間存活的回應，所以它整個生命週期都釘在同一個副本上。在**另一個**副本上發布的 `ctx.notify_resource_updated(...)` 必須送得到它。

兩者之間的接縫是 `SubscriptionBus`。給伺服器什麼 bus，每次發布就進到那個 bus，每個開著的串流也都在上面聽，所以把同一個 bus 交給每個副本：

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

扇出完全不在乎串流掛在哪個伺服器物件上。兩個伺服器共用一個 `InMemorySubscriptionBus` 本來就是這樣運作：在其中一個上開啟 listen 串流，在另一個上 `edit_note`，串流就會聽到。那個記憶體內的 bus 只能跨越同一個處理程序裡的伺服器物件，所以它是模型，不是部署方案：

* 跨真正的處理程序時，**SDK 沒有附任何幫得上忙的 bus。**`SubscriptionBus` 是一個只有兩個方法的 `Protocol`（`publish` 和 `subscribe`），由你在自己的 pub/sub 後端（Redis、NATS，或你已經在跑的任何東西）上實作，再以 `MCPServer(subscriptions=...)` 傳入。草稿與契約請見 **[訂閱](../handlers/subscriptions.md#scaling-past-one-process)**。
* bus 載的是四種小型的有型別事件，從來不是 JSON-RPC。確認、過濾和串流生命週期都留在 SDK 裡，所以你的 bus 不可能破壞協定；它只能在處理程序之間搬運事件。
* 串流**不能**續傳，事件也**不會**重播。失去一個副本就丟掉它的串流；用戶端會重新 listen、重新抓取。沒有要共用的事件儲存區，也沒有別的要設定。這是唯一一個向外擴展真的只是「多幾台一樣的」的地方。

## SDK 不提供的東西 {#what-the-sdk-does-not-give-you}

`MCPServer` 是協定實作，不是應用程式伺服器。接下來你會去找的部署選項是刻意不放的：

* **沒有 `workers=`。**`mcp.run("streamable-http")` 啟動剛好一個 uvicorn 處理程序，而且永遠只會啟動這一個。多處理程序就是把 `streamable_http_app()` 交給你本來就拿來部署 ASGI 的東西：`uvicorn --workers`、gunicorn、平台的處理程序管理器。本頁刻意不當其中任何一個的教學；它們的說明文件比在這裡抄一份要好。
* **沒有健康檢查路由。**`@mcp.custom_route("/health", methods=["GET"])` 就是全部答案，而且即使伺服器其他部分需要驗證，它也永遠不需要。這對存活探測是對的，對任何私密的東西是錯的。**[加入現有應用程式](asgi.md#custom-routes)** 有一個範例。
* **沒有正式環境設定物件。**`MCPServer` 上沒有地方寫下逾時、TLS、優雅關閉或連線上限，因為這些都不是它的工作。它們屬於你的 ASGI 伺服器，在那裡設定。**[執行伺服器](index.md)** 涵蓋建構子**確實**接受的那幾個設定。
* **沒有附 `EventStore`，而且在 2026-07-28 上也用不著。**可續傳是舊版有狀態那一支的功能；現代的交換就是一個 POST、一個回應，沒有什麼要續傳。

## 重點回顧 {#recap}

* 預設情況下，這個應用程式只回應送往 localhost 的請求。`transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` 是上線的關卡：在傳入它之前，真正主機名稱後面的每個請求都是 `421`，原因只在伺服器記錄裡。
* 在 2026-07-28 上沒有工作階段，負載平衡器也沒有東西可黏。`stateless_http=True` 是只給舊版用的開關，因為現代請求在那個旗標被讀到之前就已經分流並回應了。
* 預設的 `requestState` 金鑰是 `os.urandom(32)`，每個處理程序各自鑄造。送到不同 worker 的多輪往返重試會以 `-32602`「Invalid or expired requestState」失敗。
* 解法是 `RequestStateSecurity(keys=[...])` **加上**每個執行個體相同的伺服器名稱。名稱是權杖預設的 audience 宣告。相同的金鑰，相同的名稱。
* 變更通知透過一個共用的 `SubscriptionBus` 跨越副本。SDK 唯一的實作是處理程序內的；在你自己的 pub/sub 上寫那個兩方法的 `Protocol` 是你的事。
* 沒有 `workers=`、沒有健康檢查路由、沒有正式環境設定物件。自備 ASGI 伺服器。

真正的主機名稱前面需要的另一樣東西是權杖：**[授權](authorization.md)**。
