---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# 執行伺服器 {#running-your-server}

`mcp.run()` 會啟動伺服器。

唯一要做的決定是**傳輸方式**：伺服器和用戶端之間的位元組實際上怎麼移動。

## 選一種傳輸方式 {#pick-a-transport}

| 傳輸方式 | 是什麼 | 何時用 |
|---|---|---|
| `stdio` | MCP 主機（host）把你的檔案當成子處理程序啟動，透過它的 stdin 和 stdout 溝通。 | 本機伺服器。預設值。 |
| `streamable-http` | 真正的 HTTP 伺服器，監聽一個連接埠。 | 任何要部署的東西。 |
| `sse` | 較舊的 HTTP 傳輸方式。 | 不要用。 |

!!! warning
    SSE 在 2025-03-26 協定修訂版中已被 Streamable HTTP 取代。`mcp.run(transport="sse")` 仍然可用，也有自己的 `sse_path=` 和 `message_path=` 選項，但它是為了還沒搬過去的用戶端而留著的。不要在它上面建任何新東西。

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` 是同步的。伺服器活著多久，它就阻塞多久。
* 不帶引數時，傳輸方式是 `stdio`。
* 它放在 `if __name__ == "__main__":` 底下，因為所有會載入伺服器的東西（`mcp dev`、`mcp run`、`mcp install`、你的測試）都是 **import** 這個檔案。這道防護讓 import 不會變成一個正在執行的伺服器。

### stdio {#stdio}

沒有什麼要設定的。主機把你的檔案當成子處理程序啟動，把請求寫進它的 stdin，再從它的 stdout 讀回應。

自己執行看看就知道後果：

```console
python server.py
```

什麼都不會印出，也不會結束。它在 stdin 上等主機先開口。

這也表示 stdout **就是線路本身**。服務期間，SDK 會把線路移到一個私有的檔案描述元，並把 **flush** 到 stdout 的輸出（子處理程序寫入它繼承來的 stdout、flush 過的 `print()`）改導到 stderr，在那裡不會弄壞串流。在開始服務**之前**就 flush 到 stdout 的輸出（包裝指令稿的 echo、匯入時未緩衝的 print）仍然會落到線路上；一直緩衝到直譯器結束時才清空的 `print()` 也一樣。真正想要的輸出，用 `logging` 模組才是正確的工具：它的 handler 會在每筆記錄發生時就 flush 到 stderr。完整說明請見 **[記錄](../handlers/logging.md)**。

### 試試看 {#try-it}

```console
uv run mcp dev server.py
```

Inspector 做的事和真正的主機一模一樣：把 `server.py` 當成子處理程序啟動，透過 stdio 連上它。

你從來沒給它連接埠。根本沒有。

## Streamable HTTP {#streamable-http}

要改把同一個伺服器放到連接埠上，就在 `run()` 裡指名傳輸方式（和它的選項）：

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

這一行會建立一個 Starlette 應用程式，並用 uvicorn 提供服務。用戶端連到 `http://127.0.0.1:3001/mcp`。

每種傳輸方式都有自己的關鍵字引數，全都在 `run()` 上：

* `host` / `port`：在哪裡監聽。預設為 `127.0.0.1` 和 `8000`。
* `streamable_http_path`：MCP 端點的位置。預設為 `/mcp`。
* `json_response=True`：每個 POST 都用單一 JSON 本體回應，而不是 SSE 串流。那個本體只裝得下回應本身，別的都沒有，所以在請求中途回頭呼叫用戶端的工具（`ctx.elicit()`、取樣（sampling））在這一段會引發 `NoBackChannelError`，而綁在進行中呼叫上的通知（`ctx.report_progress()` 的進度、每次呼叫的記錄訊息）會被丟棄；獨立的 `GET` 串流仍會承載不相關的那些。
* `stateless_http=True`：每個請求一個全新的傳輸，不追蹤工作階段（session）。
* `max_request_body_size`：可接受的最大 POST 本體，以位元組計。預設為 4 MiB；更大的請求在解析或建立工作階段之前就會收到 HTTP 413。只有在合法的 MCP 訊息超過這個大小時才調高它。
* `event_store`、`retry_interval`、`transport_security`：可續傳性與 DNS 重新綁定防護。這些可以先放著，等到部署到 localhost 以外的地方再說；`transport_security` 在 **[部署與擴展](deploy.md)** 有說明。

!!! warning
    傳輸選項是給 `run()` 的，**不是**給 `MCPServer(...)`。建構子描述伺服器**是什麼**：名稱、版本、說明文字（instructions）。`run()` 描述它怎麼被提供服務。弄反了，Python 在 MCP 根本還沒介入之前就會回你：

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` 是捷徑。一旦需要更多（伺服器掛載在現有的應用程式裡、一個處理程序裡兩個伺服器、給瀏覽器用戶端的 CORS），就自己建立 ASGI 應用程式，再交給任何一個 ASGI 伺服器執行。那是 **[加入現有應用程式](asgi.md)**。

## 伺服器設定 {#server-settings}

關於執行，有幾件事和傳輸無關。它們是建構子引數：

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`：在建構 `MCPServer(...)` 的當下就交給 `logging.basicConfig()`。那會設定 **root** logger，所以也會設定你自己 logger 的層級，不只是 SDK 的。預設為 `"INFO"`。
* `debug`：轉交給 HTTP 傳輸建立的 Starlette 應用程式。預設為 `False`。

兩者都會落在 `mcp.settings` 上，執行時可以讀回來。

## `mcp` 命令 {#the-mcp-command}

`[cli]` extra 會安裝一個把這些包起來的小命令列工具。

`mcp dev` 在 **MCP Inspector** 底下執行伺服器：

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` 把套件加進它建立的環境；`--with-editable` 把你自己的套件安裝進去。它需要 `PATH` 上有 `npx`：Inspector 是 Node.js 應用程式。

`mcp run` 會匯入檔案、找出伺服器物件（模組層級的 `mcp`、`server` 或 `app`），然後對它呼叫 `run()`：

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

物件不叫 `mcp`、`server` 或 `app` 時，用 `:` 後綴指名它。

你的 `if __name__ == "__main__":` 區塊在這裡永遠不會執行：`mcp run` 自己呼叫 `run()`，而它唯一轉交的選項是 `--transport`。

`mcp install` 把伺服器註冊到 **Claude Desktop**，讓那個應用程式替你啟動它：

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` 和 `-f .env` 會把環境變數記錄在那筆項目裡。Claude Desktop 在它自己的處理程序裡啟動伺服器。你的 shell 環境不在那裡。

`mcp install` 只認得 Claude Desktop 這一個主機。其他每個主機（Claude Code、Cursor、VS Code）都在自己的設定檔裡接受同樣的啟動命令，**[連接真正的主機](../get-started/real-host.md)** 每一個都有。

`mcp version` 印出已安裝的 SDK 版本。

!!! tip
    `mcp dev` 和 `mcp run` 只懂 `MCPServer`。如果用低階的 `Server` 來建，就要自己執行它。請見 **[低階 Server](../advanced/low-level-server.md)**。

## 重點回顧 {#recap}

* **傳輸方式**是位元組抵達伺服器的方式：本機子處理程序用 `stdio`，連接埠用 `streamable-http`。SSE 已被取代。
* `mcp.run()` 選擇傳輸方式。不帶引數就是 `stdio`，而且會阻塞。
* 每個傳輸選項（`host`、`port`、`streamable_http_path`……）都是 `run()` 的引數，絕不是 `MCPServer(...)` 的。
* 把 `run()` 放在 `if __name__ == "__main__":` 底下。所有載入伺服器的東西都會先 import 這個檔案。
* `log_level=` 和 `debug=` 是建構子引數；它們落在 `mcp.settings` 上。
* `mcp dev` 開 Inspector，`mcp run` 執行檔案，`mcp install` 給 Claude Desktop，`mcp version` 看版本。
* 傳輸方式永遠不會改變伺服器**是什麼**：這一頁的三個檔案公開的是一模一樣的工具。

當 `run()` 本身成了限制（伺服器在一個已經存在的應用程式裡），就看 **[加入現有應用程式](asgi.md)**。真正的主機名稱和不只一個 worker，是 **[部署與擴展](deploy.md)**。如果有些用戶端還停在規格版本 2025-11-25 或更早，**[服務舊版用戶端](legacy-clients.md)** 有好消息。
