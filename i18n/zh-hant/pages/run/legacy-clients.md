---
translation:
  sections: [3d1663c18edc824c, d4fd37009a13f03d, af9f398a5a8b679a, 470c2dd144294d69, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# 服務舊版用戶端 {#serving-legacy-clients}

MCP 有兩個協定世代：`initialize` 交握世代，到規格版本 `2025-11-25` 為止；以及現代世代 `2026-07-28`。專門講這個分界的頁面是 **[協定版本](../protocol-versions.md)**。

這一頁談的是這個分界的伺服器端，而答案一句話就講完：**你已經部署的 `streamable_http_app()` 兩個世代都能服務。**

SDK 依每個請求的 `MCP-Protocol-Version` 標頭來路由。標明 `2026-07-28` 的請求交給現代處理路徑。標明交握世代版本的請求，或是根本沒帶標頭的請求（2026 之前的用戶端送來的 `initialize` 就是這樣到達的），則交給那些用戶端預期的傳輸：`initialize` 交握、工作階段（session），一樣不少。這一切逐請求發生，在你的程式碼之前，在同一個應用程式上。

所以，舊版用戶端不是你要特地**為它**打造什麼東西；它只是會**連上**你已經寫好的伺服器。什麼都不用設定。

!!! note
    真的是什麼都沒有。沒有 `legacy=` 選項，沒有版本允許清單，沒有任何方法可以拒絕或停用某個世代：`streamable_http_app()` 上沒有、`run()` 上沒有、工作階段管理器上也沒有。兩個世代永遠都開著。那個簽章裡最接近「依世代切換」的東西是 `stateless_http`，而這一頁大半都在講它。

## 一個處理函式，兩個世代 {#one-handler-both-eras}

下面是一個必須問使用者問題的工具，以及兩個世代的用戶端呼叫它：

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` 需要一樣模型沒有提供的東西：要幾本。`Annotated[..., Resolve(ask_quantity)]` 就是工具宣告這件事的方式（完整說明請見 **[相依性](../handlers/dependencies.md)**）。`reserve` 裡沒有任何地方指名版本、檢查能力或做分支。

兩個用戶端**同時**開著，連到同一個 `mcp` 物件。`mode="legacy"` 會執行 `initialize` 交握：正是 2026 之前的用戶端會開啟的那種連線。另一個用預設值，落在 `2026-07-28`。

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

同一個伺服器、同一個處理函式、同一個答案。整個功能就這樣。

值得停下來看看**怎麼做到的**，因為這兩個用戶端是透過兩條完全不同的線路被問了同一個問題。`2026-07-28` 連線沒有讓伺服器送出請求的通道，所以 `Resolve` 把問題放在工具結果裡回傳，用戶端再帶著答案重試這次呼叫（**[多輪往返請求（multi-round-trip）](../handlers/multi-round-trip.md)**）。`2025-11-25` 連線沒有這種機制；在那裡，`Resolve` 在呼叫途中送出即時的 `elicitation/create` 請求並等待。兩者你都沒寫。`Resolve` 讀取連線協商出的版本然後挑選；不管哪一種，工具本體看到的都是 `AcceptedElicitation`。

!!! tip
    這種跨世代可攜性正是 `Resolve` **為什麼**是該拿來當基礎的 API。它的前輩 `ctx.elicit()`（**[徵詢（elicitation）](../handlers/elicitation.md)**）永遠只會送 `elicitation/create`，所以永遠只在舊版連線上有效。在 `2026-07-28` 連線上，這個呼叫會失敗。如果某個工具還在用它，修正方法就是上面看到的那樣，而不是加版本檢查。

## 舊版工作階段的代價 {#what-a-legacy-session-costs-you}

路由是免費的。工作階段不是。

`2026-07-28` 連線是**無工作階段**的：每個請求各自獨立，現代處理路徑從不發出 `Mcp-Session-Id`。舊版連線正好相反。2026 之前的用戶端一送出 `initialize`，SDK 就鑄造一個 `Mcp-Session-Id`，放在回應標頭裡回傳，並在背後保留一筆活的紀錄，讓用戶端之後的請求找得到：協商出的版本、開著的串流、一個驅動工作階段的背景任務。

那筆紀錄是一個**普通的、處理程序內的 `dict`**。沒有分散式工作階段儲存區，也沒有辦法外掛一個。

只有一個 worker 時，這完全看不出來。有兩個時，這就是全部的問題所在：帶著 `Mcp-Session-Id` 的請求如果落到不是鑄造它的那個 worker 上，在那個 dict 裡什麼都找不到，得到的答案是 `404`（`Session not found`），而不是工具結果。所以只要執行超過一個 worker，**舊版用戶端就需要黏性路由**：一個工作階段裡的每個請求都必須抵達開啟它的那個處理程序。現代用戶端永遠不需要；它們沒有工作階段可黏。黏性和其他關於執行多個實例的一切，請見 **[部署與擴展](deploy.md)**。

!!! warning
    `event_store=` 看起來像解法，但不是。它是**可恢復性**（把漏掉的 SSE 事件重播給重新連回**同一個**工作階段的用戶端），不是工作階段儲存區。它永遠不會讓工作階段能從另一個處理程序存取到。

## 唯一的開關：`stateless_http` {#the-one-knob-stateless_http}

如果黏性是你不願付的代價，能改的東西剛好只有一樣。

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

這是頁面最上方的那個伺服器再加一個關鍵字。`stateless_http=True` 讓舊版路徑改為建立用過即丟、每個請求一個的工作階段：不發 `Mcp-Session-Id`，請求之間什麼都不記，所以任何 worker 都能服務任何請求，負載平衡器想怎麼分就怎麼分。

關於它，有兩件事比它做什麼更重要。

**它只影響舊版路徑。** 請求在讀取 `stateless_http` **之前**就已依版本標頭路由好了，所以現代路徑根本看不到它。`2026-07-28` 連線本來就無工作階段，在兩種值下完全一樣。

**它的代價是那條路徑上的兩個伺服器到用戶端通道。** 只活一次 `POST` 的工作階段，沒有串流讓伺服器推送請求，也沒有獨立串流讓它推送通知。每個伺服器發起的請求都會引發 `NoBackChannelError`：`ctx.elicit()`、已退役的取樣（sampling）與根目錄（roots）呼叫（**[已棄用的功能](../deprecated.md)**），還有，沒錯，`Resolve` 向**舊版**用戶端提問時也一樣。通知甚至連錯誤都沒有，就默默被丟掉。

!!! note
    `json_response=True` 不是那個開關，但它在**每個**舊版工作階段上都會付出一半同樣的代價：用單一 JSON 本體回應的 `POST` 沒有串流可供請求範圍的通道使用，所以請求途中的 `ctx.elicit()` 會引發同樣的 `NoBackChannelError`，綁在該請求上的通知則被丟掉。工作階段的獨立串流不受影響：不相關的通知照樣送達。

!!! check
    故意做錯一次。`reserve` 正是剛剛服務了兩個用戶端的那個工具。用 `stateless_http=True` 部署它，透過 HTTP 連上同樣的兩個用戶端，從各自呼叫它。

    現代用戶端還是得到 `Reserved 2 of 'Dune'.`，現代路徑沒變。

    舊版用戶端的呼叫不會以模型讀得到的 `is_error` 結果回來。整個請求失敗，成為頂層的協定錯誤：

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` 沒救到你。在 `2025-11-25` 連線上它**必須**送出 `elicitation/create`，而它需要的通道正是 `stateless_http=True` 放棄掉的東西。跨世代可攜的程式碼，不等於不需要反向通道（back-channel）的程式碼。

所以這是真實的取捨，而且只存在於舊版路徑上：**有工作階段且黏性，或無狀態且單向。** 如果你的工具從不回頭呼叫用戶端，`stateless_http=True` 就是免費的，應該採用。如果會，就保留工作階段，並讓路由保持黏性。

## 你的程式碼真正分岔的地方 {#where-your-code-actually-forks}

幾乎沒有。

工具、資源、提示詞、結構化輸出、進度、錯誤：沒有一個在乎是哪個世代呼叫的。`initialize` 交握、`Mcp-Session-Id`、獨立串流、結束工作階段的 `DELETE`：全部由 SDK 掌管，處理函式一個都看不到。互動式輸入是兩個世代在線路上**真正**不同的那個地方，而 `Resolve` 的存在就是為了讓它不成為你的問題：你剛剛才看到一個工具同時服務兩者。

剩下的剛好只有一件事，就是**變更通知**，因為兩個世代聽的是不同的管道：

* `2026-07-28` 用戶端開啟一條 `subscriptions/listen` 串流並讀取訂閱匯流排。`ctx.notify_resource_updated()`（以及 `notify_tools_changed()`、`notify_prompts_changed()`、`notify_resources_changed()`）發佈到那裡，而且**只**發到那裡。那一頁是 **[訂閱](../handlers/subscriptions.md)**。
* 舊版用戶端讀的是它的工作階段保持開啟的獨立串流。`ctx.session.send_resource_updated()`（以及 `send_tool_list_changed()` 等）寫到承載該請求的**連線**：對舊版工作階段來說，就是它的獨立串流。現代連線沒有地方放它：透過 HTTP 時沒有這種通道，透過 stdio 時這四種變更通知只搭 `subscriptions/listen` 串流，所以在現代連線上這個通知會被默默丟掉。

透過 HTTP，兩個呼叫都到不了另一個世代的用戶端。要通知所有人，兩個都呼叫：

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

兩行，沒有 `if`，沒有版本檢查，就完成了。這就是處理函式因為舊版用戶端存在而要做得不一樣的事的完整清單。

## 重點回顧 {#recap}

* 一個 `streamable_http_app()` 服務兩個協定世代。SDK 依每個請求的 `MCP-Protocol-Version` 標頭路由；沒有東西要設定，也沒有世代開關可找。
* 舊版用戶端的代價是一個工作階段：一筆處理程序內的 `Mcp-Session-Id` 紀錄，背後沒有分散式儲存區。超過一個 worker 就表示要**黏性路由**，否則錯的 worker 會回 `404 Session not found`。多 worker 的完整說明請見 **[部署與擴展](deploy.md)**。
* `stateless_http=True` 是唯一的開關，而且**只作用於舊版路徑**。它用那條路徑上的兩個伺服器到用戶端通道，換來舊版用戶端的自由負載平衡：伺服器發起的請求會引發 `NoBackChannelError`（在用戶端是頂層錯誤，不是 `is_error` 結果），通知則被丟掉。
* `2026-07-28` 連線不管怎樣都無工作階段。`stateless_http` 永遠碰不到它。
* 處理函式的程式碼只在一個地方依世代分岔：變更通知。`ctx.notify_*` 到得了 `subscriptions/listen` 用戶端；`ctx.session.send_*` 到得了舊版工作階段。兩個都呼叫。
* 其他一切（包括透過 `Resolve` 向使用者要輸入）在設計上就是跨世代可攜的。現代的寫法寫一次就好。
