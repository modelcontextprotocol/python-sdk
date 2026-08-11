---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# 用戶端傳輸方式 {#client-transports}

每個 `Client` 都透過一種**傳輸**（transport）和伺服器溝通：也就是實際承載訊息的那個東西。

你從來不需要單獨設定它。`Client` 只接受一個位置引數，並依據它的型別判斷要用哪一種傳輸方式。

每種傳輸方式的**伺服器**端（`mcp.run()` 做的事，以及你部署的東西）請見 **[執行伺服器](../run/index.md)**。

## 記憶體內 {#in-memory}

直接傳入伺服器物件本身：

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

沒有子處理程序，沒有連接埠，線路上也沒有任何位元組。用戶端和伺服器是同一個處理程序裡的兩個物件，但呼叫仍然會經過真正的協定層：`search_books` 被列出、驗證、呼叫的方式，和透過 HTTP 時完全一樣。

所以它同時是兩樣東西：

* **測試工具。** 這份說明文件裡的每個範例都是這樣跑過的，而 **[測試](../get-started/testing.md)** 那一頁整個模式就是圍繞它建立的。
* **嵌入用的 API。** 自己建立伺服器的應用程式，不需要繞一圈網路就能呼叫它的工具。

## Streamable HTTP {#streamable-http}

傳入一個 URL 字串，得到的就是 **Streamable HTTP**，也就是部署時使用的那種傳輸方式：

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

這就是完整的正式環境用戶端。`Client` 會替你把 URL 包進 `streamable_http_client(...)`，底下是一個依 MCP 需求設定好的 `httpx2.AsyncClient`：`follow_redirects=True`、connect/write/pool 的逾時為 30 秒，read 逾時則是 300 秒，因為伺服器可能會讓回應串流一直開著。

!!! check
    建立好的 `Client` **還沒有**連線。建立只是選定傳輸方式；真正開啟它的是 `async with`。在進入之前就去拿連線，SDK 會直接告訴你：

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    寫下 `Client("http://...")` 的時候，沒有解析、抓取或啟動任何東西。那一行是零成本的。

### 自備 `httpx2.AsyncClient` {#bring-your-own-httpx2asyncclient}

一旦需要 `Authorization` 標頭、cookie、proxy、mTLS，或不同的逾時，就自己建立 `httpx2.AsyncClient`，再交給 `streamable_http_client`：

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

有兩件事要注意：

* `httpx2.AsyncClient` 是你的，所以由**你**負責進入和離開它。SDK 永遠不會關閉不是它自己建立的用戶端。
* `streamable_http_client(url, http_client=...)` 回傳的是一個傳輸，而 `Client(transport)` 和接受其他東西一樣接受它。

關於 TLS 有一點要提：`httpx2` 是對照作業系統的信任存放區驗證憑證（透過 [`truststore`](https://pypi.org/project/truststore/)），而不是內建的 CA 清單。在沒有可用系統 CA 存放區的環境（某些精簡容器）裡，請設定標準的 `SSL_CERT_FILE`/`SSL_CERT_DIR` 環境變數，或明確傳入 `verify=ssl_context` 給你的 `httpx2.AsyncClient`（背景說明請見 [`httpx` 和 `httpx-sse` 已由 `httpx2` 取代](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)）。

!!! warning
    `streamable_http_client` 以前可以直接接受 `headers=` 和 `timeout=`。現在不行了：它僅有的參數是 `url`、`http_client` 和 `terminate_on_close`。如果習慣性地寫了 `headers=`，會得到：

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    所有跟 HTTP 有關的設定，現在都放在你傳入的那一個 `httpx2.AsyncClient` 上。

!!! info
    `httpx2` 保留了熟悉的 `httpx` API，所以只要會用 `httpx`，就已經知道這裡的驗證、proxy、事件掛鉤、重試和連線數限制該怎麼做。SDK 沒有在上面加任何東西，也沒有拿掉任何東西。OAuth 也是從這裡接上的：`httpx2.AsyncClient(auth=OAuthClientProvider(...))`。整個流程請見 **[OAuth 用戶端](oauth-clients.md)**。

## stdio {#stdio}

**stdio** 伺服器是一個子處理程序。用戶端啟動它，把 JSON-RPC 寫進它的 stdin，再從它的 stdout 讀取 JSON-RPC。桌面版 MCP 主機（host）就是這樣在你的機器上執行伺服器的：主機**就是**這段程式碼加上一個 UI，而 **[連接到真正的主機](../get-started/real-host.md)** 則是從主機那一側、以設定檔的形式看同一個關係。

用 `StdioServerParameters` 描述這個處理程序，用 `stdio_client` 把它變成傳輸，再把**那個**交給 `Client`：

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` 不接受單獨的參數物件。`StdioServerParameters` 是設定；`stdio_client(server)` 才是知道怎麼依據它啟動處理程序的傳輸。一定要包起來。

離開 `async with` 區塊時，子處理程序也會一併關閉：關掉 stdin、等待、拖太久就強制終止。你永遠不需要自己清理。

!!! warning
    子處理程序**不會**繼承你的環境。它拿到的是一份精簡的允許清單（POSIX 上是 `HOME`、`LOGNAME`、`PATH`、`SHELL`、`TERM` 和 `USER`），這樣敏感的東西才不會洩漏到一個可能不是你寫的處理程序裡。

    需要 API 金鑰的伺服器在那裡是找不到的。請用 `env=` 明確傳入；這些變數會疊加在允許清單之上。上面的 `BOOKSHOP_API_KEY` 做的就是這件事。

## SSE {#sse}

`mcp.client.sse` 裡的 `sse_client(url)` 是被 Streamable HTTP 取代的那個 HTTP 傳輸。要和還在講它的伺服器溝通，用同樣的方式包起來即可：`Client(sse_client("http://localhost:8000/sse"))`，但不要在它上面蓋任何新東西。

## `Transport` 協定 {#the-transport-protocol}

對 `Client` 來說，上面這些全都是同一種東西。

**傳輸**是任何會產出一對 `(read, write)` 訊息串流的非同步 context manager：正式地說，就是 `mcp.client` 裡的 `Transport` 協定。`Client` 依型別解析它的引數：伺服器物件就在處理程序內連線，`str` 會變成 `streamable_http_client(url)`，其他任何東西則直接當成傳輸進入。最後這條規則就是為什麼 `stdio_client(...)`、`streamable_http_client(...)` 和 `sse_client(...)` 都能放進同一個位置，也是為什麼你可以自己寫一個。

## 重點回顧 {#recap}

* `Client(mcp)`（伺服器物件）在記憶體內連線。用在測試和嵌入。
* `Client("http://.../mcp")`（URL）透過 Streamable HTTP 連線，也就是正式環境用的傳輸方式。
* 標頭、驗證、proxy 和逾時都放在你傳給 `streamable_http_client(url, http_client=...)` 的 `httpx2.AsyncClient` 上。沒有 `headers=` 這個關鍵字引數。
* stdio 是 `Client(stdio_client(StdioServerParameters(...)))`，絕對不是單獨的參數物件。
* 子處理程序拿到的是允許清單上的環境，不是你的環境；`env=` 會往上加。
* 傳輸就是任何可以 `async with x as (read, write)` 的東西。只要不是伺服器物件或 URL，`Client` 就會直接交給那個協定處理。
* 建立 `Client` 是選定傳輸方式。`async with` 才是開啟它。

傳輸開啟之後，兩邊得對協定版本達成一致。平常根本不需要去想這件事；真的需要的時候，請看 **[協定版本](../protocol-versions.md)**。
