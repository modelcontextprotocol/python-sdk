---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# 協定版本 {#protocol-versions}

MCP 有兩個世代。

2026-07-28 之前發佈的伺服器，每次連線都以 **`initialize` 交握**開場：用戶端提出一個版本，伺服器回一個版本，用戶端確認，這一切都發生在第一個真正有用的請求之前。**2026-07-28** 的伺服器拿掉了交握。用戶端送出一個 **`server/discover`** 探測，伺服器用單一結果一次回答全部內容。

你幾乎不需要在意這件事，因為 `Client` 會替你協商。這一頁談的是控制這件事的那一個建構子引數 `mode=`，以及需要改動它的三種情況。

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

沒有傳入 `mode`，所以拿到的是預設值：`"auto"`。進入 `async with` 時，會以這個 SDK 支援的最新版本送出一個 `server/discover` 探測。接著：

* **新世代伺服器**會回答。用戶端採用結果。一次往返，完成。
* **較舊的伺服器**從沒聽過 `server/discover`，回傳錯誤。用戶端退回傳統的 `initialize` 交握，接受它協商出的結果。

不管哪一種，最後都會連上線，而 `client.protocol_version` 會告訴你是哪一種：

```text
2026-07-28
```

整個功能就這樣。一個 `Client`，任何世代的伺服器，程式碼裡不用分支。

!!! info
    `MCPServer` 在每一種傳輸方式上都會回答 `server/discover`（記憶體內、stdio、Streamable HTTP），所以對你自己的伺服器，`auto` 永遠會落在 `2026-07-28`。退回機制只會在面對真正的 2026 之前的伺服器時觸發，而那正是你希望它觸發的時候。

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` 從不探測。它執行 `initialize` 交握，也就是 2026 之前的用戶端會開啟的那種連線。

```text
2025-11-25
```

同一個伺服器。它完全能說 `2026-07-28`；是你叫用戶端不要問的。

**推送式**的功能需要這個。

伺服器發起的請求，是伺服器反過來呼叫**你**：`ctx.elicit(...)` 把表單擺到你的使用者面前，取樣（sampling）在工具呼叫進行到一半時向你的模型要一段生成結果。這個通道只存在於交握世代的工作階段（session）上。

到了 2026-07-28 它就沒了。伺服器改成**回傳**它的問題，你帶著答案重試呼叫（**[多輪往返（multi-round-trip）請求](handlers/multi-round-trip.md)**）。

`mode="auto"` 只有在伺服器舊到別無選擇時才會給你交握。`mode="legacy"` 則保證有交握。只要你交給 `Client(...)` 一個 `sampling_callback`、一個想以請求方式驅動的 `elicitation_callback`，或一個 `message_handler`，就用它。**[用戶端回呼](client/callbacks.md)** 逐一說明。

## 釘選版本 {#pinning-a-version}

`mode` 也接受新世代的協定版本字串。目前這個集合剛好就是 `["2026-07-28"]`。

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

釘選**什麼都不送**。沒有探測，沒有交握。用戶端在本機直接採用 `2026-07-28`，`async with` 一回傳，連線就是通的。

釘選是**你**做出的承諾：你已經知道伺服器說那個版本。用戶端不會檢查。

!!! check
    釘選不是探索。印出 `client.server_info`，代價就擺在眼前：

    ```text
    None
    ```

    用戶端從沒問過伺服器它是誰，所以 `server_info` 是 `None`。`client.server_capabilities` 也一樣：每個能力都是 `None`。工具呼叫照常運作（協定完全不需要這些）；讀取 `server_capabilities` 來決定要提供什麼的程式碼就不行了。

    下一節就是解法。

只有新世代的版本可以釘選。交握世代的字串在建構時就會被拒絕，早於任何 I/O，而錯誤訊息會告訴你該改寫成什麼：

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## 用 `prior_discover` 重新連線 {#reconnecting-with-prior_discover}

探測很便宜，但它仍然是每次重新連線都要付的一次往返，而答案幾乎從來不變。

所以把它留下來。`auto` 連線之後，`client.session.discover_result` 保存著伺服器送來的那份 `DiscoverResult`：它的 `supported_versions`、`capabilities`、`instructions`，以及伺服器蓋進結果 `_meta` 裡的身分。下次把它作為 `prior_discover=` 交回去：

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

第二次連線做了**零**次協商往返，卻仍然確切知道對方是誰。這才是釘選模式的正確用法：`mode=` 指定版本，`prior_discover=` 提供身分。✨

`DiscoverResult` 是 Pydantic 模型。`saved.model_dump_json()` 存進檔案或快取；`DiscoverResult.model_validate_json(...)` 在下一個處理程序裡把它讀回來。

!!! tip
    `prior_discover=` 只有在 `mode` 是版本釘選時才有作用。在 `"auto"` 下用戶端反正會探測伺服器，在 `"legacy"` 下則會被忽略。

## 四種模式 {#the-four-modes}

| 你寫的 | 協商流量 | 你得到的 |
| --- | --- | --- |
| `Client(target)` | 一個 `server/discover` 探測；失敗的話改走 `initialize` 交握 | 雙方都支援的最新版本，不論哪個世代 |
| `Client(target, mode="legacy")` | `initialize` 交握 | 交握世代的版本；伺服器發起的請求可以運作 |
| `Client(target, mode="2026-07-28")` | 無 | 那個版本，已釘選，`server_info` 為 `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | 無 | 那個版本，已釘選，**而且**還有上次存下來的身分 |

## 重點回顧 {#recap}

* MCP 有交握世代（到 `2025-11-25` 為止，`initialize` 交握）和新世代（`2026-07-28`，`server/discover`）。`Client` 銜接兩者。
* `mode="auto"` 是預設：先探測，不行再退回。除非其他三列有一列說的是你，否則不要動它。
* `client.protocol_version` 永遠能回答「我拿到的是什麼？」。
* `mode="legacy"` 強制交握。伺服器發起的請求需要它：取樣、推送式徵詢（elicitation）、`message_handler`。
* 版本釘選（`mode="2026-07-28"`）完全不送協商流量，代價是 `client.server_info` 為 `None`。
* `prior_discover=` 把這個代價補回來：存下 `client.session.discover_result`，帶著它重新連線，兩者兼得。

新世代連線沒有推送通道，那 2026 的伺服器要怎麼在呼叫進行到一半時問你問題？它把問題回傳：**[多輪往返請求](handlers/multi-round-trip.md)**。
