---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# 安裝 {#installation}

Python SDK 在 PyPI 上的套件名稱是 [`mcp`](https://pypi.org/project/mcp/)，需要 **Python 3.10+**。

這份文件描述的是 **v2**，也就是目前的穩定版本線：

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "從 v1 過來的嗎？"
    v2 是含有破壞性變更的主要版本，**[遷移指南](../migration.md)**逐一說明了每一項變更。如果你的**套件**依賴 `mcp` 而且還沒準備好遷移，請保留 `<2` 的版本上限（例如 `mcp>=1.28,<2`），這樣沒有鎖定版本的解析結果就會停留在 1.x 版本線。

## 會安裝哪些東西 {#what-gets-installed}

使用 SDK 不需要知道這些，但如果你好奇每個相依套件的用途：

* `mcp-types`：所有協定型別（請求、結果、內容區塊）獨立成一個套件，版本與 SDK 同步。依賴 `mcp` 的程式碼透過 `mcp.types` 這個別名匯入（這份文件裡每一個 `from mcp.types import ...` 都是如此）；只有在安裝了 `mcp-types` 但沒有安裝 SDK 的專案裡，才直接匯入 `mcp_types`。
* [`anyio`](https://anyio.readthedocs.io/)：非同步執行環境。整個 SDK 都是基於 anyio 寫的，所以在 `asyncio` 或 `trio` 上都能執行。
* [`pydantic`](https://docs.pydantic.dev/)：每個 `mcp.types` 模型的基礎，也負責所有 schema 的產生與驗證。
* [`httpx2`](https://pypi.org/project/httpx2/)：Streamable HTTP 和 SSE **用戶端**傳輸背後的 HTTP 用戶端，內建 server-sent events 支援。
* [`starlette`](https://www.starlette.io/)、[`uvicorn`](https://www.uvicorn.org/)、[`sse-starlette`](https://pypi.org/project/sse-starlette/) 和 [`python-multipart`](https://pypi.org/project/python-multipart/)：HTTP **伺服器**傳輸。
* [`jsonschema`](https://pypi.org/project/jsonschema/)：依照工具宣告的輸出 schema 驗證它的結構化輸出。
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/)：授權用的 OAuth 權杖處理。
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/)：只有輕量的 API，所以除非你自己安裝 OpenTelemetry SDK 和匯出器，否則 SDK 的追蹤中介軟體不會帶來任何負擔。
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) 和 [`typing-inspection`](https://pypi.org/project/typing-inspection/)：讓 Python 3.10 也能使用新的型別功能。
* [`pywin32`](https://pypi.org/project/pywin32/)：僅限 Windows，用於 `stdio` 子處理程序管理。

## 選用的 extra {#optional-extras}

* `mcp[cli]` 會加裝 [`typer`](https://typer.tiangolo.com/) 和 [`python-dotenv`](https://pypi.org/project/python-dotenv/)，供 `mcp` 命令列工具使用（`mcp dev`、`mcp run`、`mcp install`）。開發期間會用到；部署後的伺服器可能就不需要了。
* `mcp[rich]` 會加裝 [`rich`](https://rich.readthedocs.io/)，讓伺服器記錄更好看。
