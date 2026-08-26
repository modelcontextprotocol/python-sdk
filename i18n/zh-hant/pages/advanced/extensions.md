---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# 擴充功能 {#extensions}

**擴充功能**是掛在單一識別碼之下、需要主動啟用的一組 MCP 行為。

在伺服器上，它可以貢獻工具、資源和新的請求方法，也可以包裹 `tools/call`。在用戶端上，它可以認領額外的 `tools/call` 結果形狀，並觀察廠商通知。兩端各自在自己的 `capabilities.extensions` 底下宣告，對沒有要求它的人來說什麼都不會改變。這就是契約（[SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)），而它有一條黃金法則：**擴充功能預設是關閉的**。

## 使用擴充功能 {#using-an-extension}

在建構時傳入實例：

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

完成。伺服器現在會在 `capabilities.extensions` 底下宣告 `io.modelcontextprotocol/ui`，並提供這個擴充功能貢獻的所有內容。

`Apps` 是內建的參考擴充功能，它有自己的專頁：**[MCP Apps](apps.md)**。

!!! note
    擴充功能在建構時就固定了。沒有之後可以呼叫的 `add_extension`：伺服器的能力對映表在用戶端連線期間不應該改變。

能力對映表透過 `server/discover` 傳遞，而這是 **2026-07-28** 的路徑。舊版的 `initialize` 交握沒有地方可以放它，所以舊版用戶端根本看不到這個擴充功能。設計時要考慮到這一點：擴充功能是用來**增強**伺服器的，不能成為伺服器唯一可用的方式。

## 撰寫自己的擴充功能 {#writing-your-own}

繼承 `Extension`，只覆寫需要的部分。每個方法都有預設實作。

### 識別碼 {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

識別碼是遵循規格 `_meta` 鍵語法的 `vendor-prefix/name` 字串：以點分隔的標籤（每個標籤以字母開頭，以字母或數字結尾）、一個斜線，接著是名稱。它在**類別定義時**就會驗證，所以打錯字不用等到伺服器啟動才發現：

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

前綴請用你能掌控的網域。`io.modelcontextprotocol/*` 保留給 MCP 專案本身制定的擴充功能。

### 貢獻工具 {#contributing-tools}

最小的有用擴充功能是一個工具加上一個設定對映表：

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` 回傳 `ToolBinding`。伺服器註冊每一個的方式，和你自己呼叫 `mcp.add_tool(...)` 完全一樣：同樣的 schema 產生、同樣的 `Context` 注入，全部都一樣。
* `settings()` 是在 `capabilities.extensions["com.example/stamps"]` 宣告的值。回傳 `{}`（預設值）表示宣告這個擴充功能但不帶任何設定。
* 擴充功能永遠不會拿到伺服器。它以資料的形式宣告貢獻，由 `MCPServer` 取用。沒有 `self.server` 可以修改。

而 `main()` 就是證明，一個記憶體內用戶端直接連上 `mcp`：

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### 提供自己的方法 {#serving-your-own-methods}

擴充功能可以註冊**新的請求方法**：屬於它自己的動詞，和規格定義的方法並列提供：

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` 繼承 `RequestParams`，所以 2026 的 `_meta` 信封能以一致的方式解析，處理函式拿到的是驗證過的參數，永遠不會是原始 dict。對用戶端能控制的東西設下界限：`Field(ge=1, le=100)` 會在你的程式碼為它配置任何東西之前，就拒絕離譜的 `limit`。
* `require_client_extension(ctx, EXTENSION_ID)` 是關卡：沒有宣告這個擴充功能的用戶端會收到 `-32021`（缺少必要的用戶端能力）錯誤，附帶規格要求的機器可讀 `requiredCapabilities` 內容。
* `protocol_versions=frozenset({"2026-07-28"})` 把這個方法釘在單一線路版本上。在其他任何版本，用戶端會收到 `METHOD_NOT_FOUND`，就像這個方法在那裡不存在一樣。對那個用戶端來說，它確實不存在。

方法是**嚴格附加的**。SDK 在建構時就強制這一點，而不是在執行時：

* 為規格定義的方法（`tools/list`、`completion/complete`……）建立的 `MethodBinding`，在繫結建構時就會引發 `ValueError`。核心動詞屬於伺服器。
* 兩個擴充功能繫結同一個方法時，第二個註冊時會引發例外。後寫者勝出正是外掛互相搞壞對方的方式；我們不這麼做。
* 空的 `protocol_versions` 集合也會引發例外：一個永遠無法被提供的方法是 bug，不是設定。

### 用戶端這一側 {#the-client-side}

同一個檔案的 `main()` 就是完整的用戶端故事，兩半都在裡面：

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` 宣告這個擴充功能。這些宣告會變成 `ClientCapabilities.extensions`：在 2026-07-28 連線上，這個對映表隨著每個請求的 `_meta` 信封傳送，所以伺服器在**每一個**請求上都看得到它；在舊版連線上，它則搭著 `initialize` 交握傳送。伺服器程式碼不用在意是哪一種：`require_client_extension(ctx, ...)` 和 `ctx.session.check_client_capability(...)` 在兩條路徑上都會讀取正確的來源。
* 廠商方法要往下一層用 `client.session.send_request(...)`；`Client` 只會為規格動詞長出一級方法。`send_request` 接受任何 `Request` 子類別，所以廠商請求原樣傳遞即可。

### 攔截 `tools/call` {#intercepting-toolscall}

唯一一個攔截式的掛鉤。覆寫 `intercept_tool_call` 來觀察、短路或否決工具呼叫：

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` 是驗證過的 `CallToolRequestParams`：不用碰原始 JSON 就能拿到 `params.name` 和 `params.arguments`。決定執行哪個工具呼叫的也是它：透過 `call_next` 傳入改寫過的上下文，改變的是處理函式在 `ctx` 上觀察到的東西，而不是工具的呼叫本身。線路層級的請求改寫屬於[中介軟體](middleware.md)的範疇。
* `call_next(ctx)` 執行鏈的其餘部分並回傳處理函式的結果。原樣回傳（觀察）、回傳別的東西（取代），或引發 `MCPError`（拒絕）。不管回傳什麼，都會像任何處理函式結果一樣序列化，包括 2026 世代的 `serverInfo` 身分戳記，所以短路的攔截器永遠不會產生匿名或不符 schema 的回應。
* 有多個擴充功能時，攔截器依註冊順序巢狀套疊：`extensions=[...]` 裡的第一個擴充功能在最外層。
* 預設實作是直接放行，而擴充功能從未覆寫這個掛鉤的伺服器，會保持原本的 `tools/call` 處理函式不動。沒用到的東西不用付出代價。

這個掛鉤只包裹 `tools/call`，別無其他。需要處理每一則訊息的事情，請用[中介軟體](middleware.md)。那正是它的用途。

## 使用用戶端擴充功能 {#using-a-client-extension}

**用戶端擴充功能**是從使用端看的同一份契約：掛在單一識別碼之下的一組用戶端行為。把實例傳給 `Client(extensions=[...])`，然後照常呼叫工具：

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` 回傳普通的 `CallToolResult`，和其他所有呼叫一樣。擴充功能改變的是：伺服器現在可以用 `receipt` **結果形狀**來回應 `buy`，而不是最終結果，而 `Receipts` 會在 `call_tool` 回傳之前把它完成（這裡是透過後續呼叫兌換收據）。呼叫端的程式碼完全不用動。

拿掉這個擴充功能，這一切就不存在：伺服器的關卡會拒絕沒有宣告它的用戶端（錯誤 -32021），而來自跳過關卡的伺服器的認領形狀會驗證失敗，完全符合規格對無法辨識的 `resultType` 的要求。預設關閉，線路的兩端都是。

要宣告一個**沒有**任何用戶端行為的識別碼（伺服器以這個能力為關卡，用戶端什麼都不做，就像上面的搜尋用戶端），使用 `advertise()`：

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## 撰寫用戶端擴充功能 {#writing-a-client-extension}

繼承 `ClientExtension`，只覆寫需要的部分。三種貢獻類型，各有預設實作：`settings()`、`claims()` 和 `notifications()`。

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* 識別碼遵循和伺服器相同的語法，在類別定義時驗證。
* `claims()` 回傳 `ResultClaim`：一個線路標籤、解析它的模型，以及完成它的解析器。模型必須用 `result_type: Literal["receipt"]` 釘住標籤，而且不可以繼承該動詞的核心結果型別；兩者都在認領建構時強制檢查。像 `receipt_token` 這樣的廠商欄位原樣走線路：被替換的形狀會一字不差地抵達用戶端。
* 解析器會收到解析過的模型和一個 `ClaimContext`；`ctx.session` 和 `client.session` 是同一個公開控制柄，所以後續動作就是一般的工作階段（session）呼叫。它回傳該動詞正常的 `CallToolResult`。
* `settings()` 是在 `ClientCapabilities.extensions[identifier]` 宣告的值，在 `Client` 建構時讀取一次。

`notifications()` 宣告要觀察的廠商伺服器通知：

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

處理函式一次收到一個驗證過的參數，依分派順序。它只觀察；不能否決或回覆。

兩條低調的規則。認領只在 2026-07-28 連線上生效，而能力宣告跟著它們走：在舊版連線上，認領會消失，識別碼也會跟著從宣告中移除，所以用戶端永遠不會宣告一個它會拒絕其形狀的擴充功能。另外，當你想自己拿到認領的形狀而不是交給解析器時，呼叫 `client.session.call_tool(..., allow_claimed=True)`；沒有這個旗標時，認領形狀抵達工作階段層的呼叫端會引發 `UnexpectedClaimedResult`。

### 擴充功能動詞 {#extension-verbs}

擴充功能自己的請求方法不需要用戶端註冊。廠商請求型別繼承 `mcp.types.Request`，並透過 `client.session.send_request` 送出，如[提供自己的方法](#serving-your-own-methods)所示。多一件事：當某個參數鍵必須搭上 `Mcp-Name` 標頭時（像 tasks 這類擴充功能規格對它們的動詞有此要求），請求型別要宣告 `name_param`：

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

工作階段會在每一條送出路徑上把 `params["jobId"]` 鏡射到 `Mcp-Name`，而缺少值時會明確失敗，而不是默默省略必要的標頭。

## 擴充功能不能做的事 {#what-an-extension-cannot-do}

貢獻介面是刻意**封閉**的。在伺服器上：設定、工具、資源、方法、一個 `tools/call` 攔截器。在用戶端上：設定、結果認領、通知繫結。擴充功能不能：

* **伸手進外層的伺服器或用戶端。**它只宣告資料，不持有任何伺服器或用戶端的參考。
* **取代核心行為。**規格方法和核心結果標籤在建構時就會被拒絕（`initialize` 直接由執行器保留）；被核心詞彙遮蔽的通知繫結則會靜默並發出警告。
* **延後註冊。**`MCPServer(...)` 或 `Client(...)` 回傳之後，擴充功能集合就定了。

如果你在跟這些牆對抗，你寫的就不是擴充功能，而是 fork。這些牆本身就是功能：讀到 `extensions=[Apps(), Stamps()]` 的使用者，就知道這兩個東西**所有**可能碰過的地方。
