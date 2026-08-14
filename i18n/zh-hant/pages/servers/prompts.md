---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
  tool: 1
---
# 提示詞 {#prompts}

**提示詞**是使用者挑選的訊息範本。

工具是給模型用的。提示詞正好相反：使用者從用戶端的選單（斜線指令、按鈕）裡選一個，填好引數，算繪出來的訊息就會進入對話，就像是使用者自己打的一樣。

宣告的方式是在回傳文字的函式上加 `@mcp.prompt()`。

## 第一個提示詞 {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK 讀取的三樣東西和工具一樣：

* **名稱**是函式名稱：`review_code`。
* 用戶端顯示的**描述**是 docstring：`Review a piece of code.`
* **引數**來自參數。`code` 沒有預設值，所以是必填。

這就是用戶端從 `prompts/list` 拿回來的內容：

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

這裡沒有 JSON Schema。提示詞的引數是一串扁平的**具名字串值**：是給人填的表單，不是給模型組出來的 payload。

### 算繪 {#rendering-it}

用戶端用 `prompts/get` 算繪範本，並傳入引數。函式會執行，回傳的 `str` 變成**一則使用者訊息**：

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

提示詞的一生就這樣：依名稱列出、需要時算繪、丟進聊天裡。

!!! check
    `required` 會在函式執行前就強制檢查。算繪 `review_code` 時不給 `code`，請求本身就會以 JSON-RPC 錯誤（錯誤碼 `-32603`）失敗：

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    這裡沒有工具那種可以交回給模型的錯誤結果，因為根本沒有模型參與：呼叫會直接引發例外。原因（`Missing required arguments: {'code'}`）會記在伺服器記錄裡。

### 試試看 {#try-it}

用 MCP Inspector 執行伺服器：

```console
uv run mcp dev server.py
```

打開 **Prompts** 分頁並選擇 `review_code`。Inspector 會畫出一個表單，裡面有一個必填的 `code` 欄位。填好、算繪，拿回來的就是上面那則使用者訊息。

## 不只一則訊息 {#more-than-one-message}

程式碼審查是一則訊息。偵錯則是一段對話，而提示詞可以替整段對話起頭。

改成回傳訊息清單，而不是 `str`：

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` 和 `AssistantMessage` 來自 `mcp.server.mcpserver.prompts.base`。交給它們一個 `str`，它們會幫你包成 `TextContent`。角色就是類別名稱。
* `Message` 是它們共同的基底類別，用它當作回傳型別註記。

現在算繪 `debug_error` 會依序產生三則訊息：

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

注意最後一則。預先填好一輪 `assistant` 的回合，就是引導模型**下一個**回覆的方法，不必讓使用者自己打出引導的話。

## 標題與引數描述 {#titles-and-argument-descriptions}

`review_code` 是函式名稱，不是標籤。給用戶端更適合放在按鈕上的文字，並描述每個引數，讓表單自己說明清楚：

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` 是給人看的名稱，和工具的 `title` 完全一樣。
* `Annotated[str, Field(description=...)]` 和 **[工具](tools.md)** 用來描述工具參數的寫法相同。在這裡描述會落在引數上，而不是 schema 裡。
* `language` 有預設值，所以不再是必填。

`prompts/list` 的項目現在帶齊了用戶端畫出好表單所需的一切：

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    如果讀過 **[工具](tools.md)**，這一頁的內容你都已經會了。同樣的裝飾器、同樣以 docstring 當描述、同樣的 `Annotated`/`Field`。唯一不同的是由誰觸發（使用者），以及結果去哪裡（進入對話）。

## 重點回顧 {#recap}

* 在函式上加 `@mcp.prompt()`，它就成為提示詞。名稱取自函式，描述取自 docstring。
* 提示詞**由使用者控制**：用戶端列出來，使用者挑一個並填入引數。
* 引數是一串扁平的具名字串（沒有 schema）。有預設值的參數就是選填。
* 回傳 `str` 會變成一則使用者訊息。回傳 `UserMessage`／`AssistantMessage` 的清單，可以替多輪對話起頭。
* `title=` 和 `Field(description=...)` 是用戶端放在 UI 上的內容。
* 缺少必填引數會讓整個請求失敗，沒有個別提示詞的錯誤結果。

伺服器端替提示詞（或資源範本）引數做自動完成，請見 **[自動完成](completions.md)**。
