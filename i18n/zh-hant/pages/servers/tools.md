---
translation:
  sections: [e4cc390d56573409, 8566e2b68594e9ad, 2c97b9f888398951, 048e5471dfa71aea, 3076b1e16ad95950, edbedf2a16e71311, 3d8ef8da89fa87c1, f6c0e02e6ea5a363]
  tool: 1
---
# 工具 {#tools}

**工具**是模型可以呼叫的函式。

在一個普通的 Python 函式上加上 `@mcp.tool()`，就宣告了一個工具。整個 API 就這樣。

## 你的第一個工具 {#your-first-tool}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/tools/tutorial001.py"
```

看看剛才寫的東西。沒有 schema、沒有 JSON、沒有協定，就只是一個函式。SDK 從中讀取三樣東西：

* 工具的**名稱**就是函式名稱：`search_books`。
* 模型看到的**描述**就是 docstring：`Search the catalog by title or author.`
* 模型可以傳入的**引數**來自型別提示：`query: str` 和 `limit: int`。

### 輸入 schema {#the-input-schema}

SDK 從這些型別提示產生一份 JSON Schema，並在 `tools/list` 時送給用戶端：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"title": "Limit", "type": "integer"}
  },
  "required": ["query", "limit"],
  "title": "search_booksArguments"
}
```

兩個引數都在 `required` 裡，因為都沒有預設值。等一下就會修正這點。（`title` 鍵是 Pydantic 產生的附帶產物；屬性、它們的型別和 `required` 才是契約。）

!!! tip
    這裡的型別提示不是說明文件，而是**契約**。如果用戶端送來 `"limit": "ten"`，SDK 會在函式執行之前就拒絕它。

### 模型收到什麼 {#what-the-model-gets-back}

用 `{"query": "dune", "limit": 5}` 呼叫這個工具，結果有兩個部分：

```python
result.content             # [TextContent(text="Found 3 books matching 'dune' (showing up to 5).")]
result.structured_content  # {'result': "Found 3 books matching 'dune' (showing up to 5)."}
```

`content` 是**模型**讀取的文字。`structured_content` 是給**用戶端應用程式**的型別化資料。它之所以存在，是因為你把回傳型別宣告成 `-> str`。

先不用管 `structured_content`。從工具回傳真正的 Python 物件，該發生的事就會發生；**[結構化輸出](structured-output.md)**那一頁專門講這件事。

### 試試看 {#try-it}

用 MCP Inspector 執行伺服器：

```console
uv run mcp dev server.py
```

打開它印出的 URL，切到 **Tools** 分頁，呼叫 `search_books`。

Inspector 會呈現一個表單，裡面有一個必填的 `query` 文字欄位和一個必填的 `limit` 數字欄位。這個表單是從你的型別提示建出來的。其他每一個 MCP 用戶端也都會這麼做。

## 選填引數 {#optional-arguments}

替參數加上預設值，它就不再是必填。就這樣，就只是 Python 而已。

```python title="server.py" hl_lines="7"
--8<-- "docs_src/tools/tutorial002.py"
```

schema 跟著變：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

`limit` 離開了 `required`，多了 `"default": 10`。省略它的用戶端會得到 `10`，和 Python 的行為一模一樣。

## 用 `Field` 寫出更豐富的 schema {#richer-schemas-with-field}

型別提示已經能做很多事，但有時候會想**描述**一個引數，或是替它加上限制。

把型別包進 `Annotated`，再加上 Pydantic 的 `Field`：

```python title="server.py" hl_lines="12-14"
--8<-- "docs_src/tools/tutorial003.py"
```

三樣新東西，全都在參數上：

* `Field(description=...)`：每個引數各自的描述，模型會和 docstring 一起讀。
* `Field(ge=1, le=50)`：數值範圍。在 schema 裡會變成 `"minimum": 1, "maximum": 50`。
* `Literal["fiction", "non-fiction", "poetry"]`：列舉。模型只能從中挑一個。

!!! check
    限制條件不是裝飾。用 `limit=999` 呼叫這個工具，SDK 會**在函式執行之前**就回應一個工具錯誤：

    ```text
    Input should be less than or equal to 50
    ```

    這個錯誤會當作工具結果回到模型手上，模型讀了之後會用合法的值重試。你只寫了一次 `le=50`，就平白得到會自我修正的 agent。

!!! info
    如果用過 FastAPI 或 Pydantic，這些你早就會了。同一個 `Field`、同一個 `Annotated`、同一套驗證。這裡沒有任何 MCP 特有的東西要學。

## 以模型作為參數 {#a-model-as-a-parameter}

當工具的引數超過兩三個，就把它們整理成一個 Pydantic 模型：

```python title="server.py" hl_lines="8-11 15"
--8<-- "docs_src/tools/tutorial004.py"
```

`Book` 的 schema 會巢狀放進工具的輸入 schema（以 `$defs` 參照的形式），模型把它填成一個 JSON 物件，而你的函式收到的是一個**真正的 `Book` 實例**，已經驗證完畢，有 `.title`、`.author` 和 `.year` 屬性。

可以自由搭配：一般參數和模型參數並列、巢狀模型、模型的 list。從頭到尾都是 Pydantic。

## `async def` {#async-def}

如果工具會做 I/O（呼叫 API、讀檔案、查資料庫），就宣告成 `async def`，在裡面 `await`。SDK 會 await 它。

一般的 `def` 工具也可以：SDK 會在執行緒裡執行它，所以永遠不會阻塞伺服器。

沒有其他要設定的東西。

## 名稱、標題與 annotations {#names-titles-and-annotations}

SDK 推斷出來的所有東西，都可以在裝飾器裡覆寫：

```python title="server.py" hl_lines="7-10"
--8<-- "docs_src/tools/tutorial005.py"
```

* `title` 是給 UI 用、方便人閱讀的名稱。用戶端會顯示「Search the catalog」而不是 `search_books`。
* `annotations` 是給用戶端的行為**提示**：
  * `read_only_hint=True`：這個工具不會改變任何東西。
  * `open_world_hint=False`：它操作的是一組封閉的東西（這份目錄），不是開放的網路。
  * 另外兩個 `destructive_hint` 和 `idempotent_hint` 描述的是會**寫入**的工具：它可能刪除東西嗎？呼叫兩次和呼叫一次的結果一樣嗎？規格只針對非唯讀的工具定義這兩個，所以放在 `search_books` 上沒有意義。

守規矩的用戶端會用它們來判斷像「執行這個之前需要先問使用者嗎？」這類事情。它們是提示，不是安全機制。永遠不要指望用戶端一定會遵守。

!!! tip
    如果不想從函式名稱和 docstring 推導，`@mcp.tool()` 也接受 `name=` 和 `description=`。大多數時候用推導的就好。

## 重點回顧 {#recap}

* 在函式上加 `@mcp.tool()` 就把它變成工具。名稱來自函式，描述來自 docstring。
* 型別提示**就是**輸入 schema。預設值讓引數變成選填。
* `Annotated[..., Field(...)]` 加上描述和限制；`Literal` 加上列舉。
* 要接收結構化的「body」，就用 Pydantic 模型參數。
* 不合法的引數會替你擋下來，並附上模型讀得懂、能據以修正的錯誤。
* I/O 用 `async def`，其他一律用一般的 `def`。

**[結構化輸出](structured-output.md)**講的是你 `return` 的值接下來會發生什麼事。
