---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# 疑難排解 {#troubleshooting}

這一頁的每個標題都是 SDK 產生的錯誤原文，底下說明它代表什麼，以及一步到位的修正方式。用瀏覽器的頁內搜尋，在這裡找到 traceback（或伺服器記錄）的最後一行，然後只讀那一則就好。

有好幾則都是針對同一個伺服器執行的。一個工具和一個範本資源，各自在遇到不認識的城市時引發例外：

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

這一頁引用的錯誤都是真的：SDK 自己的測試套件會重現每一個。

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

這不是 MCP 的錯誤，而是 anyio 的雜訊，真正的錯誤在貼出內容的**最後一行**。

`Client.__aenter__` 會啟動一個 task group。anyio 會把任何離開 task group 的東西包進 `ExceptionGroup`，所以**每一個**逃出 `async with Client(...)` 區塊的例外，不管是什麼，都會包在裡面送到你手上：

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

對此有兩件事要做：

1. **讀最底下。** `MCPError: No forecast for 'Atlantis'.` 才是失敗本身；在這一頁找**它的**文字。
2. **在區塊內攔截。** 只有當例外**離開** `async with` 時才會出現 `ExceptionGroup`。在裡面攔截的話，同樣的失敗就是單純的 `MCPError`，哪裡都沒有 group：

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    **連線**期間的失敗（URL 錯了、伺服器沒在執行、這一頁後面的 `421`）是從 `async with` 本身逃出來的，所以沒有「裡面」可以攔截。遇到這些，就讀 group 的最底下。

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` 只是建立物件。在 `async with` 之前什麼都不會連線，所以每個方法都會拒絕：

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

進入它。`__aenter__` 就是連線：

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` 就是斷線，這也是為什麼沒有 `client.close()` 可以忘記。**[測試](get-started/testing.md)** 正是建立在這個模式上。

## `Error executing tool <name>: <message>` 與 `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

你讀到的是**結果**，不是例外。`call_tool` 沒有引發例外，而且遇到失敗的工具它永遠不會引發。

用伺服器不認識的城市呼叫 `forecast`，它引發的例外會跟著一個標記為**成功**的請求一起回來：

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

對於伺服器從未註冊的名稱，`Unknown tool: get_forecast` 也是同樣的形狀；錯誤的引數也一樣，在你的函式執行之前，就會依工具的輸入 schema 遭到拒絕。

修正在用戶端：**檢查 `result.is_error`**。包在 `call_tool` 外面的 `try/except` 一個都攔不到，因為根本沒有東西可以攔。這是刻意的設計，也是這一頁最值得內化的一件事：是**模型**選擇了這個呼叫，所以訊息交給模型，讓它有機會再試一次。完整說明請見 **[處理錯誤](servers/handling-errors.md)**，包括**確實會**引發例外的 `MCPError` 路徑。

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

你寫了 `@mcp.tool` 而不是 `@mcp.tool()`。`tool()` 是裝飾器**工廠**：少了括號，Python 會把你的函式交給它的 `name=` 參數。

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

加上括號。同樣的手誤，`@mcp.resource(...)` 和 `@mcp.prompt()` 也會說同樣的話。

!!! note
    這在模組**匯入**時就會引發，早於任何用戶端連線。所以如果主機（host）把伺服器顯示成「failed to start」（或「disconnected」），而不是已連線但零個工具，就是這種情況：自己執行 `python server.py`，讀 traceback。型別檢查器也抓得到：函式不是合法的 `name=`。

## `Tool already exists: <name>` {#tool-already-exists-name}

兩次註冊用了同一個工具名稱。**第一個**勝出，第二個會被默默丟掉，而**伺服器記錄**裡的這則警告是唯一的訊號：

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` 只回報一個 `forecast`，而且是 `forecast_today`。把其中一個改名。`MCPServer(..., warn_on_duplicate_tools=False)` 會讓警告安靜，但結果不變，所以保持開著。資源和提示詞有同樣的規則和同樣的記錄行（`Resource already exists:`、`Prompt already exists:`）。

## 主機列出零個工具 {#my-host-lists-zero-tools}

這個沒有錯誤字串，正因如此才難搜尋。SDK 從不會把已註冊的工具從 `tools/list` 丟掉，所以從內往外一層層檢查：

* **伺服器到底有沒有啟動？** 沒有括號的 `@mcp.tool` 會在匯入時引發例外，而當掉的伺服器在某些主機裡看起來很像空的伺服器。自己執行 `python server.py`。
* **工具是在主機執行的那個 `mcp` 上嗎？** 另一個模組裡的第二個 `MCPServer(...)` 是另一個空的伺服器。確認主機的指令實際匯入的是哪個物件。
* **有兩個工具同名嗎？** 那其中一個就不見了。在伺服器記錄裡找 `Tool already exists:`。
* **主機的清單過期了嗎？** 啟動後才新增的工具，只會送達會處理 `notifications/tools/list_changed` 的用戶端。重新啟動主機是最直接的解法。
* **有東西在轉向區間之外寫入 `stdout` 嗎？** 服務期間，SDK 會把**已 flush** 的雜散 stdout 轉到 stderr（盡力而為：會替換標準串流的環境就照原樣服務），但更早就 flush 到 stdout 的輸出（包裝腳本的 echo、無緩衝處理程序裡匯入時的 `print()`），或是在直譯器結束時才排出的緩衝 `print()`，都會落到協定串流上，而一行垃圾就可能讓主機斷線，有些主機會把這呈現成一個空無一物的伺服器。改用 `logging` 模組記錄。其餘的主機端檢查清單在 **[連接真正的主機](get-started/real-host.md)**。

「無效的」工具名稱**不在**這份清單上：不合規範的名稱會記錄一則警告，但工具照樣會註冊並列出。

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

伺服器直接拒絕了這個 HTTP 請求，而且本文不是 JSON-RPC，所以 python `Client` 沒有更好的東西可以顯示，只能給這個替代訊息。

最常見的原因，遠遠超過其他的，是剛部署好的 Streamable HTTP 伺服器。沒有 `transport_security=` 的 `streamable_http_app()`（以及 `mcp.run("streamable-http")`）預設為 **DNS rebinding 防護**：只接受 `Host` 標頭是 localhost 的請求。在筆電上這是對的預設值，放在真正的主機名稱後面就錯了：

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

把它部署出去，讓用戶端指向它，連線會在交握時失敗：

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

伺服器實際送出的字眼 `421` 和 `Invalid Host header` 永遠到不了你手上：421 的本文沒有 `Content-Type: application/json`，所以用戶端無法解析。它們在**伺服器的記錄**裡，那就是下一步該看的地方：

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

修正是 `transport_security=`。把實際服務的主機名稱加入允許清單：

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    整個改動就這樣。一模一樣的用戶端現在連得上，協商出 `2026-07-28`，並呼叫 `forecast`。

**[部署與擴展](run/deploy.md)** 說明每個欄位的意義、反向代理的情況，以及其他所有在部署時會變的東西。而緊接在下面的 `421 Misdirected Request` / `Invalid Host header`，是從另一邊看到的同一個失敗。

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

這就是 `Server returned an error response`，只是從**不是** python `Client` 的任何東西看到的：curl、瀏覽器的網路分頁、反向代理的存取記錄，或是另一個 SDK。

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` 是 HTTP 自己對這個狀態碼的原因短語；`Invalid Host header` 是 SDK 的回應本文；而 python `Client` 把同一個事件呈現為 `Server returned an error response`。三者是同一次拒絕。檢查的對象是**請求帶的 `Host` 標頭**，不是伺服器綁定的位址，所以轉送公開主機名稱的反向代理會和直連的用戶端一模一樣地觸發它。

修正和 `Server returned an error response` 底下示範的一樣：`transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`。有兩個邊界情況值得一提：

* `allowed_hosts` 的項目是完全比對的字串。`"mcp.example.com"` 比對不帶連接埠的 `Host` 標頭，`"mcp.example.com:*"` 比對任何明確寫出的連接埠。兩個都列。
* 本文為 `Invalid Origin header` 的 `403` 是針對 `Origin` 標頭的姊妹檢查。它只對瀏覽器觸發（別的東西都不送 `Origin`），而 `allowed_origins=` 是它的允許清單。

完整說明請見 **[部署與擴展](run/deploy.md)**，包括什麼時候把檢查關掉才是老實的設定。

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

你的 MCP 應用程式掛載在另一個 ASGI 應用程式裡，卻沒有任何東西啟動它的**工作階段管理器**（session manager）。

`mcp.streamable_http_app()` 回傳一個 Starlette 應用程式，它自己的生命週期會啟動這個管理器，而 `uvicorn server:app` 會替你執行那個生命週期。但 Starlette **從不執行被掛載的子應用程式的生命週期**，所以應用程式一放進 `Mount`，管理器就永遠不會啟動，第一個請求就炸開：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

伺服器啟動了。路由也解析得到。然後 `uvicorn` 對每個請求都印出這個：

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

用戶端看到 500。修正是在**外層**應用程式上加一個會進入 `mcp.session_manager.run()` 的生命週期：

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

這件事的專頁是 **[加入既有的應用程式](run/asgi.md)**，包括一個應用程式裡放好幾個伺服器以及 FastAPI 的情況。同一個類別還有兩個相鄰的字串：

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` 管理器只能用一次；同一個應用程式的生命週期進入兩次就會撞上它。
* `mcp.session_manager` 要等呼叫過 `streamable_http_app()` **之後**才存在，所以先建好路由，只在生命週期裡面碰管理器。

## `MCPError: Session not found` {#mcperror-session-not-found}

伺服器不認得用戶端送來的 `Mcp-Session-Id`，幾乎都是因為伺服器**重新啟動了**（或是你被導到另一個實例）。工作階段存在那一個處理程序的記憶體內。

沒有伺服器的 bug 可找。HTTP 回應是 `404`，而它的本文**就是** JSON-RPC，所以和上面的 `421` 不同，python `Client` 會原封不動地把這個顯示給你：

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

修正是重新連線：離開 `async with Client(...)` 區塊，進入一個新的，它會協商出新的工作階段。對於長時間存活的用戶端，這表示在呼叫外面攔截 `MCPError`，遇到這個訊息就重新連線，而不是在已經死掉的工作階段裡重試。

如果**沒有**重新啟動也發生，代表你跑了不只一個 worker 卻沒有黏性工作階段（sticky session）：每個 worker 都有自己的工作階段表，所以導到錯誤 worker 的請求就會落到這裡。這件事和它的兩種修正（黏性路由，或 `stateless_http=True`）請見 **[部署與擴展](run/deploy.md)** 和 **[服務舊版用戶端](run/legacy-clients.md)**。

對伺服器維運人員來說，對應的記錄行是 `Rejected request with unknown or expired session ID: <id>`。它以 `INFO` 層級記錄，所以在常用的 `WARNING` 門檻下看不到。剛部署完看到它一陣陣冒出來是正常的；每個已連線的用戶端都在重新連線。

## `MCPError: Method not found` {#mcperror-method-not-found}

某一邊送出了另一邊沒有處理函式的 JSON-RPC 請求，`e.error.data` 會寫出是哪個方法。常見原因是**世代不合**：某個方法存在於一個協定修訂版而不在另一個，卻送給了講錯版本的對端，例如 `2025` 世代的 `resources/subscribe` 送到 `2026-07-28` 連線，或是固定在 `mode="legacy"` 的用戶端送出只有 `2026` 才有的 `subscriptions/listen`。哪一邊講什麼的對照圖在 **[協定版本](protocol-versions.md)**，而另一個正當的原因（你從未替它註冊處理函式的選用能力）在 **[自動完成](servers/completions.md)**。

有一件事**不會**產生這個錯誤，儘管它是現代協定已移除的請求：工具在 `2026-07-28` 連線上呼叫 `ctx.elicit()`。伺服器根本拒絕**送出**那個請求，所以你得到的反而是這一頁後面的 `Cannot send 'elicitation/create': ...`。

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

伺服器想問使用者一件事，而這個用戶端從沒說過它可以被問。

徵詢（elicitation）解析器在已連線的用戶端沒有宣告表單徵詢時，會一開始就拒絕，而 `e.error.data` 會精確寫出缺了什麼：

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

把 `elicitation_callback=` 傳給 `Client(...)`。註冊回呼**就是**能力宣告；沒有第二個開關：

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[用戶端回呼](client/callbacks.md)** 列出其他的（`sampling_callback`、`list_roots_callback`），每一個同樣都是宣告。

!!! info
    `-32021` 是 `MISSING_REQUIRED_CLIENT_CAPABILITY`，是 2026-07-28 規格新增的三個錯誤碼之一。它們都不是例外類別：全部以 `MCPError` 送達，要看的是 `e.error.code`。`mcp.types` 匯出了這些常數。另外兩個是 `-32020` `HEADER_MISMATCH`（HTTP 標頭和它伴隨的請求本文不一致）和 `-32022` `UNSUPPORTED_PROTOCOL_VERSION`（請求指定了這個伺服器不會講的版本）。符合規範的 SDK 用戶端兩者都產生不了，所以如果看到其中一個，去查是什麼東西在用戶端和伺服器之間改寫請求。

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

和 `Client did not declare the form elicitation capability ...` 是同一個缺口，只是出自那些不會事先檢查的路徑：伺服器需要有人回答一個徵詢，而已連線的用戶端沒有註冊 `elicitation_callback`。

在舊版連線上的 `ctx.elicit()` 會看到它；而在任何連線上，只要回傳的多輪往返（multi-round-trip）問題（**[多輪往返請求](handlers/multi-round-trip.md)**）送到了沒有回呼可以回答的用戶端，也會看到它。修正一模一樣：把 `elicitation_callback=` 傳給 `Client(...)`。沒有任何一種「使用者沒被問到」會以 `decline` 的形式送到你的工具；問不了的用戶端就是一次失敗的呼叫，所以設計工具時要考慮這點。

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

處理函式試圖在請求途中聯繫用戶端，但這條連線上的這次呼叫沒有能承載伺服器發出請求的通道。有三種伺服器設定會讓呼叫落到這種處境。

**`2026-07-28` 連線：任何傳輸方式，一律如此。** 現代協定完全沒有伺服器發起的請求，所以伺服器在送出任何東西之前就拒絕。工具裡的 `ctx.elicit()` 是遇到這個的典型方式（就在第一次記憶體內測試時，因為 `Client(server)` 不用交代就會協商出 `2026-07-28`），而傳入 `elicitation_callback=` 什麼都不會改變，因為根本沒有請求送到用戶端讓它回答：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**`stateless_http=True` 伺服器上的舊版連線。** 無狀態表示每個請求都自成一個世界：沒有工作階段、沒有伺服器到用戶端的串流，所以即使是有這些方法的世代，也無處可送 `elicitation/create`（或 `sampling/createMessage`、或 `roots/list`）：

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**`json_response=True` 伺服器上的舊版連線。** `POST` 是以一個 JSON 本文回應的，而一個本文只裝得下回應，所以請求途中的 `ctx.elicit()` 需要的請求範圍串流在這裡也不存在。工作階段、它的 `Mcp-Session-Id` 和它的獨立串流都還在；只有請求範圍的通道不見了。

訊息會寫出它送不出去的方法。伺服器引發的類別是 `NoBackChannelError`，但線路上只載得了基底的 `MCPError`，所以 traceback 的最後一行是上面那句話，而不是類別名稱。

對 `2026-07-28` 用戶端來說，三種情況的修正都一樣：不要在呼叫途中回頭聯繫。把問題移進**解析器**（或自己回傳一個 `InputRequiredResult`），它就變成**回應**的一部分，而每條連線都載得了回應：

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

同樣的問題，用戶端上同樣的 `elicitation_callback`。差別在底層：解析器讓伺服器從呼叫中**回傳**問題，而不是推送出去，所以從頭到尾沒有任何東西從伺服器流向用戶端。這救得了每一個 `2026-07-28` 用戶端，不管伺服器是三種設定中的哪一種。**舊版**用戶端光靠改寫救不了：`2025-11-25` 沒有辦法回傳問題，所以在舊版連線上，解析器還是會沿著請求範圍的通道送出 `elicitation/create`，也還是需要一個保留這條通道的伺服器，既不是 `stateless_http=True` 也不是 `json_response=True`。解析器請見 **[徵詢](handlers/elicitation.md)**；線路上發生什麼事請見 **[多輪往返請求](handlers/multi-round-trip.md)**。

!!! check
    用 `ctx.elicit()` 的工具沒有錯，它只是 **2026 之前**的寫法。用 `mode="legacy"`（傳統的 `initialize` 交握，規格 `2025-11-25` 及更早）連到一個既不是 `stateless_http=True` 也不是 `json_response=True` 的伺服器，它就能運作，因為那裡有伺服器到用戶端的通道。每個版本有什麼請見 **[協定版本](protocol-versions.md)**。

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

伺服器無法驗證用戶端回送的 `requestState` 權杖，所以拒絕了這一輪。

`requestState` 是 **[多輪往返](handlers/multi-round-trip.md)** 呼叫在各段之間攜帶的不透明續接權杖。`MCPServer` 在送出時密封它，並驗證每一次回送；而且它會驗證 `tools/call`、`prompts/get` 和 `resources/read` 上**每一個**進來的 `request_state`，就算處理函式從不產生權杖也一樣。所以不是這個處理程序密封的權杖，不管落在哪裡都會被拒絕：

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

這則訊息是刻意固定不變的：線路上永遠不會透露是哪一項檢查失敗。原因會寫進**伺服器記錄**，讀它就是全部的診斷：

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

實際上會看到的原因：

* **`unknown key`** 是最要緊的一個。預設的密封金鑰在處理程序啟動時產生，所以落到**另一個 worker**、負載平衡器後面另一個實例，或是**重新啟動後**的同一台伺服器上的重試，當初是用這個處理程序從沒有過的金鑰密封的。那不是攻擊者；是預設值遇上了不只一個處理程序。
* **`audience`**：權杖是由**伺服器名稱不同**的實例密封的。名稱是密封預設的 audience claim，所以一整批實例除了金鑰之外，也必須共用名稱（或設定明確的 `RequestStateSecurity(audience=...)`）。
* **`expired`**：這一輪花的時間超過密封的 `ttl`，它是 600 秒，而且是每輪計算，不是每次呼叫。
* **`malformed`** / **`codec error`**：權杖在傳輸途中被改過，或者根本從來不是密封過的權杖。
* **`request binding`**：權杖回來時帶的是不同的工具、不同的引數，或不同的方法。

多處理程序的修正是一個引數（每個實例上**相同**的 `keys`）加上一個根本不是引數的東西：相同的伺服器**名稱**（或明確共用的 `audience=`）。

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` 負責密封；清單裡的每一把金鑰都能驗證，這正是零停機輪替得以實現的原因。密封保護了什麼以及輪替順序，請見 **[多輪往返請求](handlers/multi-round-trip.md#protecting-requeststate)**；整個雙 worker 失敗情境和它的兩段式修正，**[部署與擴展](run/deploy.md)** 會完整走一遍。

!!! tip
    `keys=[...]` 會立刻拒絕太弱的金鑰，訊息格外貼心：

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    照它說的做就好。

## 還是卡住？ {#still-stuck}

* 如果 SDK 產生的某則訊息不在這一頁上，那本身就是值得回報的文件 bug。
* 搜尋 [issue tracker](https://github.com/modelcontextprotocol/python-sdk/issues)；出現在那裡的錯誤字串，大多已經有人寫過紀錄了。
* 什麼都沒找到？附上完整的 traceback [開一個 issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)，或到 [MCP Contributors Discord 的 #python-sdk-dev](https://discord.gg/6CSzBmMkjX) 發問。

## 重點回顧 {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` 永遠不是錯誤本身。讀**最後一行**；在 `async with Client(...)` 區塊**裡面**攔截 `MCPError` 就完全跳過包裝。
* `call_tool` 不會因為工具失敗而引發例外。`Error executing tool ...` 和 `Unknown tool: ...` 是結果：檢查 `result.is_error`。
* `Client must be used within an async context manager` -> 用 `async with`。`Use @tool() instead of @tool` -> 加上括號。
* 伺服器記錄裡的 `Tool already exists:` 是兩個同名工具合併成一個的唯一跡象。
* 一個 421，三種寫法：`Server returned an error response`（python `Client`）、`421 Misdirected Request` / `Invalid Host header`（其他所有東西）、`Invalid Host header: <host>`（伺服器記錄）。修正：`transport_security=TransportSecuritySettings(allowed_hosts=[...])`。
* `Task group is not initialized` -> 掛載的應用程式，其外層生命週期從未進入 `mcp.session_manager.run()`。
* `Session not found` -> 伺服器重新啟動了；重新連線。
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` 需要伺服器到用戶端的通道：`2026-07-28` 連線從來沒有，`stateless_http=True` 拿走了舊版的那條，`json_response=True` 拿走了請求範圍的那條。改用解析器（舊版用戶端還需要一個保留通道的伺服器）。它的鄰居 `Method not found` 則是請求了一個對方的協定修訂版沒有的方法。
* `Client did not declare the form elicitation capability ...` 和 `Elicitation not supported` -> 用戶端少了 `elicitation_callback=`。
* `Invalid or expired requestState` 在線路上從不說原因。伺服器記錄會說；`unknown key` 表示要在各 worker 之間共用 `RequestStateSecurity(keys=[...])`。
