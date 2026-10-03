---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "這裡是 v2 的說明文件，也就是目前的穩定發行版本"
    剛接觸 v2，或是從 v1 過來？**[v2 的新功能](whats-new.md)** 用五分鐘帶你看過有哪些改變，**[遷移指南](migration.md)** 則涵蓋每一項破壞性變更。還在用 v1.x？它的說明文件在 [v1.x 文件](https://py.sdk.modelcontextprotocol.io/v1/)。哪裡卡住或看不懂？[告訴我們](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

**Model Context Protocol（MCP）** 讓應用程式能以標準化的方式為 LLM 提供上下文，把**提供**上下文這件事和與 LLM 的互動本身分開。

這是它的官方 Python SDK。有了它，你可以：

* **建立 MCP 伺服器**，向任何 MCP 主機（host）公開工具、資源和提示詞。
* **建立 MCP 用戶端**，連線到任何 MCP 伺服器。
* 支援每一種標準傳輸方式：stdio、Streamable HTTP 和 SSE。

## 環境需求 {#requirements}

Python 3.10+。

## 安裝 {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` extra 會提供 `mcp` 指令，開發時會用到。每個相依套件的用途請見[安裝](get-started/installation.md)。

## 範例 {#example}

### 建立 {#create-it}

建立 `server.py` 檔案：

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

這就是一個完整的 MCP 伺服器。

它公開了一個**工具** `add`，以及一個範本化的**資源** `greeting://{name}`。

### 執行 {#run-it}

```console
uv run mcp dev server.py
```

這會啟動伺服器並開啟 [MCP Inspector](https://github.com/modelcontextprotocol/inspector)，一個可以動手操作伺服器的互動式介面。打開它印出的 URL 即可。

!!! note
    Inspector 是 Node.js 應用程式，所以 `mcp dev` 需要 `PATH` 上找得到 `npx`。

### 試試看 {#try-it}

在 Inspector 中前往 **Tools**，用 `a=1`、`b=2` 呼叫 `add`。

得到的結果是 `3`。✨

那張表單（`a` 一個必填整數欄位、`b` 另一個）是 Inspector 從型別提示建出來的。Claude 和其他所有 MCP 主機也都會這麼做。

接著前往 **Resources**，讀取 `greeting://World`：

```text
Hello, World!
```

### 重點回顧 {#recap}

再看一次你**沒有**寫的東西：

* 沒有 JSON Schema。`a: int, b: int` **就是** schema。
* 沒有請求解析、沒有序列化、不用寫驗證程式碼。
* 完全不用處理協定。

你寫了兩個帶型別提示和 docstring 的 Python 函式，剩下的交給 SDK。

## 接下來 {#where-to-go-next}

* **[開始使用](get-started/index.md)** 帶你從安裝一路走到一個可運作、經過測試的伺服器。
* 要打造**使用** MCP 伺服器的應用程式？從 **[用戶端](client/index.md)** 開始。
* 已經有 FastAPI 或 Starlette 應用程式？**[加入現有應用程式](run/asgi.md)** 教你把 MCP 伺服器掛載進去。
* 在找某個確切的錯誤訊息？**[疑難排解](troubleshooting.md)** 以原文字串為索引。
* 想知道 v2 改了什麼？**[v2 的新功能](whats-new.md)** 是五分鐘導覽。
* 從 v1 遷移？從 **[遷移指南](migration.md)** 開始。
* 在找確切的函式簽章？**[API 參考](api/mcp/index.md)** 是從原始碼產生的。
* 和 LLM 一起閱讀？這份說明文件也以 [llms.txt](https://llmstxt.org/) 格式發布：[llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) 是各頁面的索引，[llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) 則把每一頁放進單一檔案。
