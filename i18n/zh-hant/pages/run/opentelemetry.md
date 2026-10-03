---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

伺服器已經有追蹤了，什麼都不用加。

你建立的每個伺服器，都會為它處理的每則訊息發出一個 [OpenTelemetry](https://opentelemetry.io/) span。這不是你寫的，也不需要匯入。呼叫 `MCPServer(...)` 的那一刻它就在了。

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

這就是一個完整、帶追蹤的伺服器。呼叫 `search_books`，就會替它建立一個 span。低階的 `Server` 也一樣：兩者都內建追蹤。

## 你會得到什麼 {#what-you-get}

每則傳入訊息都會變成一個 `SERVER` span，名稱取自方法和它的目標。所以對 `search_books` 的 `tools/call` 就是 `tools/call search_books` 這個 span，而單純的 `tools/list` 就只是 `tools/list`。

每個 span 帶有幾個屬性：

* `mcp.method.name` 和 `mcp.protocol.version`，每個 span 都有。
* `jsonrpc.request.id`，請求才有（通知沒有）。
* 處理函式引發例外時，會把 span 狀態設為 error。`is_error=True` 的工具結果也一樣。

而因為追蹤工具呼叫是很常見的需求，`tools/call` span 採用 OpenTelemetry 的 [GenAI 語意慣例](https://opentelemetry.io/docs/specs/semconv/gen-ai/)：

* `gen_ai.operation.name`，設為 `"execute_tool"`。
* `gen_ai.tool.name`，設為被呼叫的工具。

`prompts/get` span 同理會有 `gen_ai.prompt.name`。list 類方法不帶 `gen_ai.*` 鍵，因為沒有東西可命名。

!!! tip
    追蹤 UI 之所以會把你的工具呼叫和其他 agent 的工具呼叫用同樣方式分組，靠的就是這些 GenAI 屬性。這個分組是免費得到的，不用寫任何額外程式碼。

## 想用之前，完全沒有成本 {#it-costs-nothing-until-you-want-it}

下面這一點，是「預設開啟」能讓人放心當預設的原因。

SDK 只依賴 `opentelemetry-api`，也就是 OpenTelemetry 輕量的那一半。沒有安裝 SDK 也沒有安裝 exporter 時，建立 span 是 no-op。所以伺服器現在發出的那些 span 幾乎不花你任何成本，也沒有人在收集。

哪天想**看到**它們，就安裝另一半，再把它指向某個地方：

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

照一般 OpenTelemetry 的方式設定 exporter，SDK 一直默默建立的每個 span 就全都亮起來了。伺服器程式碼不用改，一行都不用。

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) 就是這類後端之一，而且會幫你把設定做好：`pip install logfire`、`logfire.configure()`，你的 MCP span 就會出現在即時檢視中。它建構在 OpenTelemetry 之上，所以下面的內容也都適用。

## 跨越線路的追蹤 {#traces-that-cross-the-wire}

追蹤最有用的時候，是它能跟著一個請求從用戶端一路進到伺服器，呈現成一張連貫的圖。

當用戶端和伺服器都執行這個 SDK 時，這種串接是自動的。用戶端把 [W3C 追蹤上下文（trace context）](https://www.w3.org/TR/trace-context/) 注入請求，伺服器再把它讀出來，於是伺服器 span 會巢狀在同一條追蹤裡的用戶端 span 底下。這就是 [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414)，不用開口就有。

如果傳入訊息不帶追蹤上下文，例如來自非本 SDK 用戶端的請求，伺服器 span 就直接掛在伺服器端目前的 span 底下，而不是另起一條全新的孤立追蹤。

## 關掉它 {#turning-it-off}

追蹤是一個中介軟體，排在伺服器清單的第一個。如果真的想要一個完全不發出 span 的伺服器，把它拿掉：

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    那個 import 開頭有底線，這是刻意的。這個類別是暫定的，就像 [`Server.middleware`](../advanced/middleware.md) 是暫定的一樣，所以應該預期匯入路徑會改變。你幾乎不會需要這樣做：沒安裝 exporter 時 span 是免費的，所以通常的做法是讓它開著、不安裝 exporter 就好。

## 重點回顧 {#recap}

* 每個 `MCPServer` 和每個低階 `Server` 預設都會為每則傳入訊息發出一個 `SERVER` span。你什麼都不用寫。
* span 帶有 `mcp.method.name` 和 `mcp.protocol.version`；`tools/call` 和 `prompts/get` 另外帶有 GenAI 屬性，讓你的工具呼叫和其他 agent 的一樣分組。
* 在安裝 OpenTelemetry SDK 和 exporter 之前完全沒有成本，裝了之後就會亮起來，伺服器不用任何改動。
* 兩端都執行這個 SDK 時，用戶端到伺服器的追蹤上下文會自動傳播。

至於決定一個請求到底能不能執行的，是 **[授權](authorization.md)**。
