---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# 資源 {#resources}

**資源**是你公開給應用程式讀取的資料。

分界就在這裡。工具是**模型**決定要呼叫的東西；資源是**應用程式**決定要載入的東西（一個設定檔、一筆紀錄、一份文件），再放到模型面前當作上下文。

在一個普通的 Python 函式上加上 `@mcp.resource(uri)`，就宣告了一個資源。

## 第一個資源 {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

形狀和工具一樣，只多了一樣東西：**URI**。資源靠位址定位，而不是靠名稱。用戶端要的是 `config://app`，從來不是 `get_config`。

其餘的部分，SDK 照樣從函式讀出來：

* **名稱**就是函式名稱：`get_config`。
* 用戶端看到的**描述**是 docstring。
* **內容**就是你回傳的東西。

在 `resources/list` 期間，用戶端會收到：

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

當它讀取 `config://app` 時，函式會執行，回傳值以文字形式送回：

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    列出資源的成本很低。函式在 `resources/list` 期間**不會**執行，只有在 `resources/read` 時才會，而且只針對用戶端要求的那個 URI。就算公開了一千個資源，也只需要為有人打開的那幾個付出代價。

### 試試看 {#try-it}

用 MCP Inspector 執行伺服器：

```console
uv run mcp dev server.py
```

打開它印出的 URL，切到 **Resources** 分頁。`config://app` 會連同描述一起出現在清單裡。點一下，Inspector 就會讀取它：那兩行設定就在眼前。

## 資源範本 {#resource-templates}

一筆紀錄一個 URI 沒辦法擴展。在 URI 裡放一個**佔位符**，函式上加一個對應的參數：

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

URI 裡有 `{user_id}`，函式上有 `user_id: str`。整個約定就這樣。

這樣就成了**資源範本**，而且會搬家：它離開 `resources/list`，改出現在 `resources/templates/list`，以樣式而不是位址的形式呈現：

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

用戶端填入佔位符，讀取一個具體的 URI：`users://42/profile`、`users://ada/profile`。同一個函式回應所有這些 URI，比對到的值會以 `user_id` 傳入：

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

注意結果裡的 `uri`。那是用戶端要求的**具體** URI，不是範本。

!!! check
    佔位符和參數必須一致。如果把函式參數改名為 `user`，URI 卻還寫著 `{user_id}`，裝飾器會在**匯入時**就拒絕，任何用戶端都還來不及靠近：

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    不一致只可能是 bug，所以 SDK 讓帶著這種錯誤的伺服器根本啟動不了。

佔位符語法遵循 [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)：`{+path}` 用於多段的值，`{?q,lang}` 用於選用的查詢參數，還有更多。SDK 預設也會對擷取出來的值做路徑安全檢查。完整參考請見 **[URI 範本與路徑安全](uri-templates.md)**。

`get_user_profile` 也可以接受一個註記為 `Context` 的參數。SDK 會注入它，而且絕不會把它當成 URI 參數；它能提供什麼，**[Context](../handlers/context.md)** 頁面有說明。

## 回傳什麼 {#what-you-return}

不限於 `str`。替每個資源指定 `mime_type`，回傳合適的東西即可：

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` 回傳 `str`，所以原樣送出。這是最常見的情況。
* `catalog_stats` 回傳 `dict`，所以 SDK 會替你序列化成 **JSON 文字**：

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` 回傳 `bytes`，所以用戶端收到的是 `BlobResourceContents` 而不是 `TextResourceContents`，位元組以 base64 編碼後放在 `blob` 欄位裡。

同樣的規則適用於其他任何可序列化為 JSON 的東西：list、Pydantic 模型、dataclass。只要不是 `str` 也不是 `bytes`，就會變成 JSON。

`mime_type` 由你宣告，預設為 `text/plain`。SDK 從不會檢查回傳的內容來猜測它，所以沒標示的 `dict` 資源仍然會以純文字對外宣告。

!!! tip
    不想從函式推導時，`@mcp.resource()` 也接受 `name=`、`title=` 和 `description=`。如果根本沒有函式要寫，`mcp.server.mcpserver.resources` 裡有現成的 `Resource` 類別（`TextResource`、`BinaryResource`、`FileResource`、`HttpResource`、`DirectoryResource`），用 `mcp.add_resource(...)` 註冊即可。

用戶端也可以**訂閱**資源，在它變更時收到通知；那是用戶端那一半的事，寫在 **[用戶端](../client/index.md)** 裡。

## 重點回顧 {#recap}

* 在函式上加 `@mcp.resource(uri)`，它就成了資源。URI 是位址，回傳值是內容，docstring 是描述。
* URI 裡有 `{placeholder}` 就成了**範本**：它列在 `resources/templates/list` 底下，同一個函式服務所有符合的 URI。
* 佔位符名稱必須等於函式的參數名稱。弄錯的話，匯入時就會知道，不用等到正式環境。
* 函式在資源被**讀取**時執行，而不是被列出時。
* `str` 變成文字，`bytes` 變成 base64 blob，其他的都變成 JSON 文字。用 `mime_type=` 來標示。
* 工具讓模型採取行動，資源讓應用程式讀取。

第三種基本元件，由人從選單裡挑選的那種，是 **[提示詞](prompts.md)**。
