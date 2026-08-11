---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# v2 的新功能 {#whats-new-in-v2}

v2 同時發生了兩件事。**SDK 重寫了**：用戶端和伺服器底下都換了新引擎，有了一等公民的 `Client`，還有一組重新命名，v1 的程式碼在第一次 import 時就會碰上。**協定也往前走了**：v2 講的是 MCP 的 2026-07-28 修訂版，它拿掉了連線交握、工作階段（session）以及所有由伺服器發起的請求，卻不會把你現有的用戶端丟下不管。

這一頁帶你走過這兩半，每個重點一節，每節最後都指向負責該主題的頁面。它不是移植手冊。移植手冊是 **[遷移指南](migration.md)**：列出每一項破壞性變更，附上修改前後的程式碼。

!!! note "v2 是穩定版本線"
    `pip install mcp` 會安裝 2.x，**[安裝](get-started/installation.md)** 有可以直接複製貼上的安裝指令。如果 v2 有任何地方壞掉、出乎意料或拖慢你的腳步，請[告訴我們](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

## SDK：從 v1 到 v2 {#the-sdk-v1-to-v2}

### `FastMCP` 現在叫 `MCPServer` {#fastmcp-is-now-mcpserver}

高階伺服器類別改了名字，模組也跟著改。這是每個 v1 伺服器最先碰到的事，因為舊的 import 路徑是直接移除，而不是已棄用：

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

對一個用裝飾器建起來的伺服器來說，這也幾乎就是移植的全部。`@mcp.tool()`、`@mcp.resource()` 和 `@mcp.prompt()` 接受的東西跟 v1 一樣（`@mcp.resource()` 多了一個選用的 `security=` 關鍵字），輸入 schema 仍然從型別提示產生。邊角的部分：`mcp.server.fastmcp.*` 底下的所有東西現在都在 `mcp.server.mcpserver.*` 底下，`ctx.fastmcp` 變成 `ctx.mcp_server`，`get_context()` 移除了（改為宣告一個 `ctx: Context` 參數），例外基底類別 `FastMCPError` 變成 `MCPServerError`。import 對照表請見 **[遷移指南](migration.md#fastmcp-renamed-to-mcpserver)**。

### `Resolve`：向使用者要輸入的新方法 {#resolve-the-new-way-to-ask-the-user-for-input}

工具需要的東西不該全部都來自模型。v2 新增：標註了 `Resolve(fn)` 的工具參數改由你寫的函式填入，模型看不到，而那個函式可以回傳 `Elicit(...)`，把問題擺到使用者面前。這是在呼叫途中向用戶端取得任何東西的首選做法：SDK 會用該連線支援的機制把問題帶過去，對舊版用戶端是即時的徵詢（elicitation）請求，在 2026-07-28 上則是多輪往返（multi-round-trip），因此同一個工具本體兩個世代都能服務。完整說明請見 **[相依性](handlers/dependencies.md)**。

!!! note
    需要時另外兩種形式仍然可用：`ctx.elicit()` 對舊版連線上的用戶端依然有效（**[徵詢](handlers/elicitation.md)**），處理函式也可以自己回傳 `InputRequiredResult`，手動驅動每一輪，這也是取樣（sampling）和根目錄（roots）請求在 2026-07-28 上傳遞的方式（**[多輪往返請求](handlers/multi-round-trip.md)**）。

### 一等公民的 `Client` {#a-first-class-client}

v1 交給你的是三層巢狀結構：一個產出原始串流的傳輸 context manager、包在外面的 `ClientSession`，再加上手動呼叫的 `await session.initialize()`。v2 只有一個物件：

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` 接受一個伺服器物件（記憶體內、沒有傳輸，也就是測試的做法）、一個 URL（Streamable HTTP），或任何傳輸 context manager，例如 `stdio_client(...)`。進入 `async with` 就會連線並協商協定版本，不管伺服器講的是哪個世代；之後 `client.server_capabilities` 和 `client.protocol_version` 就直接在那裡，伺服器有表明身分時 `client.server_info` 也在（它現在是 `Implementation | None`，因為 2026 世代的身分是選用的）。在 v1 註冊的取樣和徵詢回呼仍然有效（回呼本體會遇到跟本頁其他地方一樣的 snake_case 屬性改名），現在也會回應 2026 風格的「結果中夾帶請求」（見下文），而且是並行執行，不再一次一個。想要低階介面的人，`ClientSession` 仍在底下，`client.session` 會把它交給你；它也有變動（跑在新的分派器引擎上，自己的部分簽章也改了），所以往下鑽之前先讀 **[遷移指南](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)**。

**[用戶端](client/index.md)** 介紹它，**[用戶端傳輸方式](client/transports.md)** 說明三種連線形式，**[用戶端回呼](client/callbacks.md)** 說明回呼本身，**[測試](get-started/testing.md)** 示範取代 v1 `create_connected_server_and_client_session()` 輔助函式的記憶體內模式。

### 低階 `Server` 是重寫，不是改名 {#the-low-level-server-was-rebuilt-not-renamed}

如果你在 JSON-RPC 層工作，這就是 v2 裡「什麼都不一樣了」的部分。下面是同一個單一工具伺服器的兩種寫法；點一下標記看看哪些東西搬了家。

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. 處理函式用裝飾器註冊（要加括號呼叫），伺服器存在之後任何時候都可以。
2. 回傳一個裸的 `list[Tool]`，SDK 會把它包成 `ListToolsResult`。
3. 欄位在 Python 裡是 camelCase，而且 schema 是**強制套用**的：SDK 會在函式執行前用 jsonschema 對照它驗證 `call_tool` 的引數，所以下面的 `arguments["query"]` 是安全的。
4. 一個 `call_tool` 處理函式服務所有工具，它收到的是工具名稱和已經驗證過的引數，已解開、永遠不會是 `None`。
5. v1 工具用引發例外來表示失敗：任何例外都會被攔截，並以 `CallToolResult(isError=True)` 回傳，文字是 `str(e)`，所以呼叫端的模型讀得到這則訊息，也可以重試。
6. 上下文來自環境中的 ContextVar，在請求途中透過伺服器物件取得。
7. 裸的內容區塊會替你包成 `CallToolResult`。

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. 欄位現在是 snake_case，而 schema 是**只公告、從不套用**：處理函式執行前沒有任何東西檢查引數。
2. 每個處理函式形狀都一樣：`async (ctx, params) -> result`。上下文是第一個引數（`ctx.session`、`ctx.request_id`、`ctx.protocol_version` 都在上面）；`server.request_context` 就是搬到這裡。
3. 完整的 `ListToolsResult` 要自己建。回傳裸的 list 現在是伺服器端的 `TypeError`，SDK 不會替你包。
4. 進來的是有型別的 params（`params.name`、`params.arguments`），出去的是完整的結果。沒有任何東西會替你解開、包裝或轉換。
5. 同樣的檢查，不同的動詞。這裡如果用 `ValueError`，到模型那邊會變成看不出內容的 `-32603`（見下文），所以刻意的線路錯誤改用 `MCPError` 引發：它會帶著原本的錯誤碼和訊息原封不動地傳過去，而帶這段文字的 `-32602` 正是規格對未知工具的標準回答。
6. `params.arguments` 可能是 `None`；v1 會在你的程式碼看到之前就把它預設為 `{}`。處理函式前面沒有驗證，這一行是不可或缺的。
7. 這裡引發的非預期例外會變成**消毒過的**協定錯誤，`-32603` `"Internal server error"`：模型永遠看不到訊息。若是模型應該讀到並做出反應的失敗，就回傳 `CallToolResult(is_error=True, ...)`。
8. 處理函式是建構子引數，所以伺服器一存在，它的介面就是完整的；`add_request_handler()` 是建構之後的逃生口，也是通往自訂方法的門。

這個範例就是模式本身。更一般地說：每個處理函式形狀都一樣，有型別的 params 進、完整的結果型別出；舊的工具引數 jsonschema 檢查拿掉了；例外就是協定錯誤，絕不會是 `is_error=True` 的工具結果；環境中的 `server.request_context` ContextVar 也拿掉了。帶廠商命名空間的自訂方法透過 `add_request_handler(method, params_type, handler)` 成為一等公民，它會在處理函式執行前用你的模型驗證傳入的 params。還有一個 `middleware` 清單（刻意標為暫定）包住每一則傳入訊息，取代大家以前會覆寫的私有 `_handle_*` 方法。

在底層，v1 的 `BaseSession` 接收迴圈換成了用戶端和伺服器現在共用的分派器引擎，本頁好幾件事能同時成立靠的就是它：一個 `Server` 物件服務兩個協定世代、`Client(server)` 在處理程序內直接分派而不經 JSON-RPC 封裝、逾時的用戶端請求現在真的會取消伺服器端的處理函式。

完整說明請見 **[低階 Server](advanced/low-level-server.md)**；**[遷移指南](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** 逐一走過每個移除的掛鉤。如果你從沒往下用到 `MCPServer` 以下的層級，這些都與你無關。

### 線路型別搬到 `mcp-types`，每個欄位都是 snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

協定型別現在有自己的發行套件 `mcp-types`。它只依賴 pydantic 和 typing-extensions，所以閘道、代理或程式碼產生器不必安裝 HTTP 堆疊就能取用 MCP 線路上的資料形狀：這類專案安裝 `mcp-types`，然後 import `mcp_types`。`mcp` 本身以精確版本依賴那個套件並重新公開它，所以依賴 SDK 的程式碼繼續寫 `import mcp.types as types` 和 `from mcp.types import Tool`（永久的別名，每個名稱都是同一個物件），並且只宣告它唯一真正的相依套件 `mcp`。經驗法則：透過你實際依賴的那個套件來 import。

在這些型別上，每個 Python 屬性現在都是 snake_case：`result.is_error`、`tool.input_schema`、`listing.next_cursor`。實際傳輸的 JSON 仍是 camelCase，跟以前完全一樣；只有屬性的拼法變了。另外跟著來的是兩個更嚴格的預設：未知欄位會被忽略而不是原樣往返（額外的東西放進 `_meta`），而且兩端都會用協商好的協定版本驗證流量。改名對照表請見 **[遷移指南](migration.md#field-names-changed-from-camelcase-to-snake_case)**。

### 傳輸設定搬到 `run()` {#transport-configuration-moved-to-run}

`MCPServer(...)` 管的是你的伺服器**是什麼**：名稱、instructions、生命週期、授權。它**怎麼提供服務**現在歸 `run()` 和各個 app 建構器管，`host`、`port`、`stateless_http`、`json_response`、端點路徑和 `transport_security` 都搬到那裡去了（`MCPServer("x", port=9000)` 是 `TypeError`）。多載依傳輸方式各自有型別，所以編輯器會告訴你 `stdio` 接受哪些選項、`streamable-http` 接受哪些。有一項移除值得知道：`mount_path` 沒了；要在前綴底下提供服務，支援的做法是掛載 ASGI 應用程式。

**[執行伺服器](run/index.md)** 說明這些選項；**[加入現有的應用程式](run/asgi.md)** 說明掛載。

### 不會出現 import 錯誤的行為變更 {#behavior-that-changes-without-an-import-error}

改名會自己跳出來提醒你。下面這些不會：

* **同步函式在工作執行緒上執行。** `def` 的工具（或資源、提示詞、解析器）不再阻塞事件迴圈；代價是它的本體不再**在**事件迴圈執行緒上執行，這對綁定執行緒的程式碼有影響。`async def` 處理函式不受影響。**[遷移指南](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**。
* **在工具裡引發的 `MCPError`（v1 的 `McpError`）現在是協定錯誤。** 模型永遠看不到它。其他所有例外仍然會變成模型讀得到、能做出反應的 `is_error=True` 結果。兩者的分界請見 **[處理錯誤](servers/handling-errors.md)**。
* **結果送出前會先驗證。** 手動建立、`input_schema` 為 `{}` 的 `Tool` 現在會讓 `tools/list` 失敗（規格要求 `"type": "object"`）。用 `@mcp.tool()` 建的伺服器不會遇到；它們的 schema 是 SDK 寫的。
* **用戶端會驗證收到的東西。** `list_tools()` 和 `call_tool()` 會用協商好的協定版本檢查伺服器的回答，所以 v1 寬鬆解析還能容忍的不太合規伺服器，現在會引發 `pydantic.ValidationError`。如果連到的是自己無法控制的伺服器，要有心理準備，發現問題的人會是你；細節請見 **[遷移指南](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)**。
* **URI 範本現在是真正的 RFC 6570。** `{+path}`、`{?query}` 這些都能用，比對是精確的而不是正規表示式那種寬鬆，擷取出的值若含路徑穿越，預設會被拒絕。更嚴格的範本會在裝飾時就失敗，而不是等到第一個請求。**[URI 範本](servers/uri-templates.md)**。
* **Streamable HTTP 的生命週期只執行一次**，在啟動時，它的狀態由所有工作階段和請求共用。v1 是每個工作階段執行一次，在 `stateless_http=True` 下則是每個請求一次。在生命週期裡建立的連線池和快取因此便宜非常多；以前在那裡取得每連線資源的東西，現在該放進處理函式本體。**[生命週期](handlers/lifespan.md)**。
* **`mcp dev` 和 `mcp install` 會把它們產生的環境釘在**你安裝的 SDK 版本上。這兩個命令都在全新的 `uv run --with ...` 環境裡執行伺服器，以前那會把 `mcp` 解析成最新的穩定版，而不是你正在開發所用的版本。**[遷移指南](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**。
* **HTTP 用戶端現在是 `httpx2`，不是 `httpx`。** 相依套件的更換改變了程式碼要攔截和傳入的東西（`httpx2.AsyncClient`、`httpx2.ConnectError`），也改變了 TLS 憑證的驗證方式：`httpx2` 透過 `truststore` 以作業系統的信任存放區驗證，而不是 certifi 內附的 CA 清單。大多數環境完全不會察覺；沒有系統 CA 存放區的極簡容器，或只有 certifi 套件包知道的私有 CA，會開始在 TLS 交握時失敗。設定 `SSL_CERT_FILE`/`SSL_CERT_DIR`，或對用戶端傳入 `verify=ssl_context`。**[遷移指南](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**。

### 直接移除 {#removed-outright}

下面每一項在 **[遷移指南](migration.md)** 裡都有一節：

* **WebSocket 傳輸**，兩端都是，以及 `mcp[ws]` extra。它從來不是 MCP 規格的一部分。
* **實驗性的 Tasks** API（`mcp.*.experimental`）。2026-07-28 把 tasks 從核心協定移到官方擴充功能（[SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)），這個 SDK 還沒實作。
* `mcp.shared.version`、`mcp.shared.progress` 和 `mcp.shared.session`（連同 v1 `message_handler` 型別註記會 import 的 `RequestResponder` 殘留類別）作為 import 路徑。（`mcp.types` **沒有**移除：它保留為獨立 `mcp_types` 套件的永久別名。）
* 已棄用的 `streamablehttp_client` 拼法，以及 `streamable_http_client` 的 `get_session_id` 回呼（它現在正好 yield 兩個串流）。
* `McpError`，改名為 **`MCPError`**，有直接的 `(code, message, data)` 建構子。
* `MCPServer.get_context()`、`mount_path=`，以及低階 `Server` 的裝飾器方法、ContextVar 和處理函式 dict。

## 協定：從 2025-11-25 到 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

v2 實作 2026-07-28 修訂版，而且**兩個**修訂版同時服務：同一個 `streamable_http_app()`（和同一個 stdio 伺服器）既回應 2025 世代用戶端的 `initialize`，也回應 2026 世代用戶端的請求，不用設定任何東西、不用切任何旗標、不用分開部署。服務新修訂版不會把停在舊版的用戶端丟下。接下來說的是新修訂版本身改了什麼。

### 沒有交握，沒有工作階段 {#no-handshake-no-session}

2026-07-28 的用戶端不會先開連線、協商、然後才講話。每個請求都在 `_meta` 裡帶著協定版本、用戶端資訊和用戶端能力，而唯一的探索呼叫 `server/discover` 就是跟其他請求一樣的普通請求。`Client` 預設就會做對的事：它探測一次 `server/discover`，如果伺服器比較舊，就退回 `initialize` 交握。

在 Streamable HTTP 上，2026 路徑沒有 `Mcp-Session-Id`，這是維運面的頭條：**沒有任何東西把現代請求綁在某個 worker 上**，所以普通輪詢式負載平衡器後面的任何副本都能回應。老實說有兩個但書。2025 世代的用戶端（今天大多數用戶端都是）仍然會開工作階段，在 v1 需要什麼黏著性現在還是需要；對它們來說什麼都沒變。另外，**多輪往返**的重試唯一必須跨 worker 帶著走的，是密封過的 `request_state`，它的預設金鑰是每個處理程序各自產生的，所以橫向擴展的部署要傳入 `RequestStateSecurity(keys=[...])`。（`stateless_http=True` 與此無關：它只影響怎麼服務 2025 世代的用戶端，2026 的流量從不讀它；如果你在 v1 就設了，什麼都不會變。）

**[協定版本](protocol-versions.md)** 是這件事的用戶端那一面，**[部署與擴展](run/deploy.md)** 是維運人員的檢查清單（Host 允許清單、`request_state` 金鑰、跨副本的通知），**[服務舊版用戶端](run/legacy-clients.md)** 則是兩個世代同時服務的完整說明。

### 伺服器不能呼叫用戶端：多輪往返請求 {#the-server-cannot-call-the-client-multi-round-trip-requests}

所有由伺服器發起的請求在 2026-07-28 都拿掉了：推送式徵詢、取樣、`roots/list`。2026 連線上沒有供它們使用的通道，所以 `ctx.elicit()` 和 `ctx.session.create_message()` 在那裡會以 `NoBackChannelError` 失敗（對舊版用戶端仍然有效）。

替代方案把呼叫反過來。需要向使用者要東西的工具**回傳**那個問題（`InputRequiredResult`），用戶端用一直都有的那些回呼回答它，然後帶著答案重試這次呼叫。那個迴圈 `Client` 會替你驅動。在伺服器上很少需要自己建那個結果，因為 **[相依性](handlers/dependencies.md)** 會做：用 `Resolve(ask_quantity)` 標註一個參數，其中 `ask_quantity` 是你寫的普通函式，SDK 就會用連線支援的機制去問，在舊版工作階段上是即時的徵詢請求，在 2026 上是多輪往返。一個工具本體，兩個世代：

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

這個檔案把整個賣點集中在一處：一個伺服器、一個以 `Resolve` 為後盾的工具，以及一個舊版用戶端加一個現代用戶端都拿到答案，全在記憶體內。**[多輪往返請求](handlers/multi-round-trip.md)** 解釋機制（包括 SDK 替你密封和驗證的 `request_state`）；**[徵詢](handlers/elicitation.md)** 說明怎麼問。

!!! warning "這是移植後的 v1 伺服器唯一會改變行為的地方"
    你自己的測試最先碰到：`Client(mcp)` 對 v2 伺服器預設協商 2026-07-28，所以呼叫 `ctx.elicit()` 的工具在 v1 通過的測試裡會失敗。把問題搬進 `Resolve(...)` 參數（跨世代可攜），或者如果真的想要推送行為，就把測試用戶端釘在 `mode="legacy"`。

### 根目錄、取樣和協定記錄已棄用；`ping` 已移除 {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) 在每個協定版本上棄用三整項**能力**：根目錄、取樣，以及 MCP 層級的記錄（`ctx.info()` 那一類）。這跟上面缺少反向通道（back-channel）是不同的軸線；已棄用只是建議性質，對 2025 世代的工作階段一切照常運作，在線路上什麼都沒變。你會注意到的是 `MCPDeprecationWarning`，它是 `UserWarning`，所以預設會印出來；升級後第一次 `ctx.info(...)` 就會這麼告訴你。

`ping` 更嚴格：是從協定移除，不是棄用。已棄用功能的兩個獨立方法在 2026-07-28 也以同樣方式移除，`logging/setLevel` 和用戶端的 `notifications/roots/list_changed`，而進度通知現在只有伺服器到用戶端這個方向。

**[已棄用的功能](deprecated.md)** 有完整的表格、每一項的替代做法，以及在服務舊版用戶端期間想讓記錄安靜下來時可用的單行篩選器。

### 變更通知變成一條串流 {#change-notifications-become-one-stream}

在 2026-07-28，獨立的 HTTP GET 串流和 `resources/subscribe` 由 `subscriptions/listen` 取代：用戶端開一條長效串流，並指名想要的通知種類。`MCPServer` 預設就會服務它；用 `await ctx.notify_resource_updated(uri)`（以及 `notify_tools_changed()` 等等）發布，中介軟體可以依呼叫端拒絕 listen 請求，多副本部署則接上共用的 `SubscriptionBus`。在用戶端，`async with client.listen(...)` 開啟串流：篩選條件以關鍵字引數傳入，回來的是有型別的變更事件，`sub.honored` 則是伺服器同意傳送的子集。

**[訂閱](handlers/subscriptions.md)** 說明發布和服務，**[用戶端那邊對應的頁面](client/subscriptions.md)** 說明監看的一端，**[部署與擴展](run/deploy.md)** 說明 bus。

### 其餘的，快速帶過 {#the-rest-quickly}

* **身分是選用的、逐訊息的中繼資料。** 請求端的 `clientInfo` `_meta` 鍵是選用的（必要的一對是 `protocolVersion` + `clientCapabilities`），而 `serverInfo` 搬出了 `server/discover` 的結果本體：伺服器改為把它蓋進每個 2026 世代結果的 `_meta`（[spec #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)）。SDK 一定會蓋；伺服器沒有表明身分時（例如中介軟體拿掉了那個鍵），`client.server_info` 是 `None`。**[低階 Server](advanced/low-level-server.md)** 展示線路上的這個戳記。
* **請求不必解析本體就能路由。** 現代 HTTP 請求帶有 `Mcp-Method`（三個類似工具的呼叫還帶 `Mcp-Name`）；標註了 `x-mcp-header` 的工具輸入 schema 屬性會鏡射到 `Mcp-Param-*` 標頭，並由伺服器交叉核對（[SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)）。閘道和限流器光靠標頭就能路由；規則請見 **[遷移指南](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)**。
* **結果帶有快取提示。** 列表和讀取結果會宣告 `ttlMs` 和 `cacheScope`（[SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)）；用 `cache_hints=` 逐方法設定，`Client` 則用內建的回應快取遵守它們。不送提示的伺服器（所有 2026 以前的伺服器）看到的是一模一樣、沒有快取的流量。**[快取提示](client/caching.md)**。
* **擴充功能是一等公民。** 伺服器和用戶端在反向 DNS 識別碼底下宣告選用的能力組合（[SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)）；內建的 `Apps` 擴充功能（MCP Apps）是參考範例。**[擴充功能](advanced/extensions.md)** 和 **[MCP Apps](advanced/apps.md)**。
* **錯誤碼標準化了。** 找不到的資源是 `-32602`，URI 放在 `error.data`，新的規格保留碼則是 `-32020`（標頭不符）、`-32021`（缺少必要能力）和 `-32022`（不支援的協定版本）。**[疑難排解](troubleshooting.md)** 以確切的訊息為索引。
* **授權更不容易用錯了。** 用戶端會驗證隨授權碼回傳的 `iss`（[RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207)；`callback_handler` 現在回傳 `AuthorizationCodeResult`），註冊時送出 `application_type`，而且絕不會對不同的授權伺服器重送憑證。企業那一角的新東西：[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 身分斷言流程。**[遷移指南](migration.md)** 列出每一項 OAuth 變更；完整說明請見 **[用戶端的 OAuth](client/oauth-clients.md)** 和 **[身分斷言](client/identity-assertion.md)**。
* **每個伺服器都可追蹤。** OpenTelemetry 以中介軟體的形式預設啟用：每個請求都有一個伺服器 span，在處理程序設定 exporter 之前完全沒有成本。兩端都跑 SDK 時，用戶端還會在 `_meta` 裡傳播 W3C trace context，所以追蹤會接起來。**[OpenTelemetry](run/opentelemetry.md)**。

## 從 v1 升級？ {#upgrading-from-v1}

* **[遷移指南](migration.md)** 是完整、精確的修改清單；本頁說的是為什麼。
* **v1.x 哪裡都不會去。** 它轉入維護，持續收到重大修正和安全性修補，2026-07-28 規格發布也沒有任何地方會弄壞它；它的說明文件在 [/v1/](https://py.sdk.modelcontextprotocol.io/v1/)。如果你發布的函式庫依賴 `mcp` 且還沒準備好遷移，保留一個上限（例如 `mcp>=1.28,<2`），讓未釘版本的解析停在 1.x。
* 哪裡卡住、看不懂或壞了？**[回報 v2 意見](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**；每一則都會有人讀。
