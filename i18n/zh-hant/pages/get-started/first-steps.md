---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# 第一步 {#first-steps}

**[首頁](../index.md)** 的節奏很快：寫一個伺服器、執行它、呼叫一個工具。

這一頁放慢腳步，把伺服器能公開的三種東西都走過一遍，沿途每樣東西都給個名字。

## 主機、用戶端與伺服器 {#host-client-and-server}

接下來每一頁都會看到這三個詞：

* **主機**（host）是 LLM 應用程式：Claude、IDE、代理執行環境。使用者對話的就是它。
* **用戶端**位於主機內部，負責講 MCP。主機每連上一個伺服器，就執行一個用戶端。
* **伺服器**是你用這個 SDK 打造的東西。它把東西公開給用戶端，從不直接和模型溝通。

伺服器由你來寫，主機是別人的產品。SDK 也提供一個 `Client`，用來測試你的伺服器，這一頁稍後就會出現。

## 三種基本元件 {#the-three-primitives}

伺服器公開的東西正好只有三種。區分它們的關鍵是**誰決定要用**：

| 基本元件      | 由誰控制         | 是什麼                                              | 範例                               |
|---------------|-----------------|-----------------------------------------------------|------------------------------------|
| **工具**      | 模型             | 模型呼叫來執行動作的函式                              | API 呼叫、寫入資料庫                |
| **資源**      | 應用程式         | 主機載入到模型上下文的資料                            | 檔案內容、API 回應                  |
| **提示詞**    | 使用者           | 使用者依名稱叫用的可重複使用訊息範本                   | 斜線指令、選單項目                  |

「由誰控制」正是這樣拆分的重點所在。工具會執行，是因為**模型**決定呼叫它。資源會被附上，是因為**應用程式**判斷模型需要它。提示詞會執行，是因為**使用者**選了它。

!!! info
    如果做過 web API，大部分直覺你已經有了：**資源**是 `GET`（載入資料，不改變任何東西），**工具**是 `POST`（做事，可能有副作用）。**提示詞**沒有 HTTP 的對應物，比較像使用者依名稱執行的已儲存查詢。

## 一個伺服器，三種齊備 {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

三個普通函式，三個裝飾器。每個裝飾器就是完整的註冊動作：

* `@mcp.tool()` 讓 `add` 成為**工具**。
* `@mcp.resource("greeting://{name}")` 讓 `greeting` 成為**資源範本**：URI 裡的 `{name}` 就是函式的參數。
* `@mcp.prompt()` 讓 `summarize` 成為**提示詞**。它回傳的字串會變成一則使用者訊息。

其他一切（名稱、描述、引數 schema）SDK 都從函式本身讀取：函式名稱、docstring、型別提示。這些你從來沒有另外宣告過。

!!! tip
    SDK 的兩半各有自己的匯入路徑：`from mcp import Client` 和 `from mcp.server import MCPServer`。沒有 `from mcp import MCPServer` 這種寫法。

### 試試看 {#try-it}

用 MCP Inspector 執行它：

```console
uv run mcp dev server.py
```

開啟它印出的 URL。Inspector 每種基本元件各有一個分頁，依序走過一遍。

**Tools。**一個項目：`add`，描述為 *Add two numbers.*。表單有一個必填的整數欄位 `a`，另一個是 `b`。填好、呼叫，結果是 `3`。Inspector 是從 `a: int, b: int` 建出那張表單的，其他每個用戶端也一樣。

**Resources。**這裡的 *Resources* 清單是空的。`greeting` 在 **Resource Templates** 底下，因為 `greeting://{name}` 帶有參數：在有人提供 `name` 之前，沒有單一資源可以列出。給它 `World` 然後讀取：

```text
Hello, World!
```

**Prompts。**一個項目：`summarize`，只有一個必填的 `text` 引數。帶一段文字去取得它，會收到一則 `role: user` 的訊息，內容就是你組好的字串。提示詞就只是這樣：一個組出訊息的函式。

Inspector 透過 **stdio** 執行你的伺服器，這是 MCP 伺服器能使用的傳輸方式之一。現在還不用選；那是 **[執行伺服器](../run/index.md)** 那一頁的事。

## 能力 {#capabilities}

在 Inspector 裡看到了三個分頁。它怎麼知道有三個？

用戶端連線時，伺服器會宣告自己的**能力**：它會回應哪幾類請求。用戶端據此決定究竟該要求什麼。這份宣告不是你寫的，`MCPServer` 替你宣告好了。

自己看看吧。SDK 的 `Client` 直接接受伺服器物件，並在**記憶體內**與它連線（沒有子處理程序，沒有連接埠）：

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

那個字典就是伺服器宣告的**能力**，也是每個連線進來的用戶端最先得知的事：

| 能力        | 用戶端現在可以呼叫                                          |
|-------------|------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                  |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                               |

`MCPServer` 三種基本元件都提供，所以三者永遠都會宣告。

注意少了什麼。`completions`（資源範本和提示詞的引數自動完成）需要你寫一個處理函式，這個伺服器沒有，所以這項能力不存在，守規矩的用戶端也不會去問。所有選用的東西都照這條規則：註冊了，能力就出現；**[自動完成](../servers/completions.md)** 會證明這一點。

!!! info
    `Client(mcp)` 就是這份文件裡每個範例測試時用的同一個記憶體內用戶端，你也會用它來測試自己的。它有專屬的一整頁：**[測試](testing.md)**。

## 你沒寫的東西 {#what-you-did-not-write}

回頭看這一頁。你寫了三個小小的 Python 函式。你**沒有**寫：

* JSON Schema。`a: int, b: int` **就是** `add` 的 schema。
* 請求處理函式。`tools/list`、`resources/read`、`prompts/get`：全都替你處理好了。
* 能力宣告。`MCPServer` 替你做了。
* 任何一行協定。版本協商、JSON-RPC 訊框、能力交換：全都發生在 `mcp dev` 和 `Client(mcp)` 裡面，你完全沒看到。

這個比例正是 SDK 的意義所在。

## 重點回顧 {#recap}

* **主機**是 LLM 應用程式，**用戶端**是它講 MCP 的那一半，**伺服器**是你打造的東西。
* 工具由**模型**控制，資源由**應用程式**控制，提示詞由**使用者**控制。
* 每種基本元件一個裝飾器：`@mcp.tool()`、`@mcp.resource(uri)`、`@mcp.prompt()`。名稱、描述和 schema 都來自函式。
* 帶 `{param}` 的 URI 會產生資源**範本**，和具體資源分開列出。
* 伺服器的**能力**會替你宣告好，而用戶端只會要求伺服器宣告過的東西。
* `Client(mcp)` 在記憶體內連上伺服器物件：從第一天起就是你的測試工具。

接下來是 **[連接真正的主機](real-host.md)**：把這個伺服器真的放進 Claude Desktop 或 IDE 裡。然後是 **[測試](testing.md)**：一頁、一個記憶體內用戶端，從此不用猜它到底能不能動。再之後，每種基本元件各有自己的一頁，從模型主導的那個開始：**[工具](../servers/tools.md)**。
