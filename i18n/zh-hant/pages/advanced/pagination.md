---
translation:
  sections: [a9aba7a026c7bd85, ed32bda7ba9ae33a, 7e64cc5646abb91f, 22a0129ee78b3c63, d875373c06d8d2f9]
  tool: 1
---
# 分頁 {#pagination}

大多數伺服器永遠用不到這個。

`MCPServer` 回應每個 `list_*` 請求時，都把手上所有東西一次給完：一頁，`next_cursor=None`。對幾十個工具、資源或提示詞來說，這就是正確的答案，沒有什麼需要設定。

分頁是給資源清單其實是資料庫的那種伺服器用的：成千上萬列，它拒絕在一個回應裡全部序列化。協定的答案是**游標（cursor）**：伺服器回傳一頁加上一個不透明的 token，用戶端把這個 token 送回去，就能拿到下一頁。

`@mcp.resource()` 沒有任何掛鉤可以做這些事。要分頁，就得在 **[低階 Server](low-level-server.md)** 上自己寫清單處理函式。

## 會分頁的伺服器 {#a-server-that-pages}

```python title="server.py" hl_lines="12 15-16"
--8<-- "docs_src/pagination/tutorial001.py"
```

* 在低階 `Server` 上，處理函式是建構子引數，不是裝飾器。`on_list_resources` 回應每一個 `resources/list` 請求；整個接線就這樣。
* 每個分頁處理函式的型別都是 `params: PaginatedRequestParams | None`，範例兩種都接受。不過在實際連線上，SDK 永遠不會交給你 `None`（沒有 `params` 成員的請求抵達處理函式時，會是帶著預設值的模型），所以真正重要的訊號是 `params.cursor is None`：**從頭開始**。
* 游標**是**什麼由你決定。這裡是轉成字串的偏移量。時間戳記、主鍵、base64 blob：任何送出時能產生、送回來時認得出的東西都可以。
* `next_cursor=None` 就是「那是最後一頁」的說法。沒有計數、沒有總數、沒有 `has_more`。`None` 就是全部的訊號。

!!! tip
    `PAGE_SIZE` 設成 10 是為了讓範例好讀。依端點各自挑選：一行就講完的資源清單，一頁 500 個也負擔得起；一堆肥大的提示詞範本清單就不行。用戶端對此沒有發言權，這是刻意的設計。

### 試試看 {#try-it}

`Client(server)` 在記憶體內連線到低階 `Server` 的方式，和連到 `MCPServer` 完全一樣。

不帶引數呼叫 `list_resources()`。會拿到十個資源，`book-1` 到 `book-10`，而 `next_cursor` 是字串 `"10"`。

用 `list_resources(cursor="10")` 把它交回去，第一個資源就是 `book-11`，新的 `next_cursor` 是 `"20"`。

第十頁回來時 `next_cursor` 是 `None`。結束。

## 用戶端迴圈 {#the-client-loop}

`Client` 上的每個 `list_*` 方法（`list_tools`、`list_resources`、`list_resource_templates`、`list_prompts`）都接受 `cursor=` 關鍵字引數。把分頁清單抓完只要一個 `while True`：

```python title="client.py" hl_lines="26-32"
--8<-- "docs_src/pagination/tutorial002.py"
```

* `cursor` 一開始是 `None`，所以第一個請求不帶游標。
* 先 extend，**再**看 `next_cursor`：最後一頁也有資源。
* `next_cursor is None` 就是出口。其他任何值都原封不動直接放回 `cursor=`。

執行它的 `main()`，會印出 `100 resources`：十頁、每頁十個，由一個從頭到尾不知道有十頁的迴圈接起來。

這和 **[用戶端](../client/index.md)** 為每個 `list_*` 動詞示範的迴圈是同一個，而且對不分頁的伺服器也沒有任何代價：第一個回應的 `next_cursor` 就是 `None`，迴圈只執行一次。

## 三條規則 {#the-three-rules}

**游標是不透明的。** 用戶端絕不能解析、組裝或猜測游標。游標唯一合法的來源，是上一頁的 `next_cursor`，一字不改。

**頁面大小由伺服器決定。** 協定裡沒有 `limit=`。如果需要不同的頁面大小，改的是伺服器。

**忽略分頁的用戶端照樣能用。** 它呼叫一次 `list_resources()`，拿到前十個，永遠不會注意到被它丟掉的 `next_cursor`。什麼都沒壞，只是看到的比較少。

!!! check
    不透明就是不透明。自己發明一個游標（`list_resources(cursor="page-2")`），協定也幫不了你。這個伺服器會嘗試 `int("page-2")`，處理函式引發例外，回到用戶端的是：

    ```text
    MCPError(-32603, 'Internal server error', None)
    ```

    不是從伺服器拿到的游標是 bug，不是功能需求。

## 重點回顧 {#recap}

* `MCPServer` 一頁回傳全部。分頁是選擇性啟用的，而啟用的地方是低階 `Server`。
* `on_list_resources`（以及 `on_list_tools`、`on_list_prompts`、`on_list_resource_templates`）收到 `PaginatedRequestParams | None`；第一頁時 `params.cursor` 是 `None`。
* 回傳一頁加上 `next_cursor`：任何之後認得出的字串，或在沒有東西剩下時回傳 `None`。
* 用戶端迴圈：傳入 `cursor=`、累積、重複，直到 `next_cursor is None`。
* 游標是不透明的，頁面大小歸伺服器管，不分頁的用戶端還是拿得到第一頁。

手寫 `Server` API 的其餘部分（`on_call_tool`、`input_schema` dict、`_meta`）在 **[低階 Server](low-level-server.md)**。
