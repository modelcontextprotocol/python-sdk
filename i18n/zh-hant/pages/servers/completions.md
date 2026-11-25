---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# 自動完成 {#completions}

用戶端如果在你的伺服器之上做一個 UI，會希望在使用者輸入時自動補上引數的值：語言名稱、儲存庫名稱、檔案路徑。

**自動完成**就是伺服器提供這些建議的方式。

## 值得自動完成的東西 {#something-worth-completing}

自動完成只適用於兩樣東西：**提示詞**的引數，以及**資源範本**的參數。所以先準備一個兩者各有一個的伺服器：

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

這裡還沒有任何跟自動完成有關的東西。

* `review_code` 接受一個 `language`。使用者不該得去猜你接受哪些拼法。
* `github_repo` 接受 `owner` 和 `repo`。兩個都放自由輸入的文字框，表單會很難用。

## 自動完成處理函式 {#the-completion-handler}

加上**一個**以 `@mcp.completion()` 裝飾的函式：

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* 每個伺服器只有一個處理函式。所有自動完成請求都會送到這裡，再依正在完成的對象分支處理。
* 必須是 `async def`：SDK 會 await 它。
* 它會收到三個引數：
  * `ref`：**哪一個**提示詞或資源範本，型別是 `PromptReference` 或 `ResourceTemplateReference`。用 `isinstance` 分辨兩者。
  * `argument`：`argument.name` 是正在完成的引數，`argument.value` 是使用者目前輸入的內容。
  * `context`：已經解析完成的引數。現在先不用管它。
* 回傳 `Completion(values=[...])`，沒有東西可建議時回傳 `None`。

!!! tip
    `argument.value` 是使用者已輸入的前綴。SDK **不會**替你過濾：放進 `values` 的是什麼，UI 就顯示什麼。`startswith` 要自己寫。

### 試試看 {#try-it}

用 **[測試](../get-started/testing.md)** 裡的記憶體內 `Client` 來操作。以 `ref=PromptReference(name="review_code")` 和 `argument={"name": "language", "value": "py"}` 呼叫 `client.complete()`：

```python
result.completion.values  # ['python']
```

* `ref` 跟處理函式收到的參照型別相同。
* `argument` 是個普通的 dict，剛好兩個鍵：`name` 和 `value`。

送出空的 `value`，就會拿回整份清單。`lang.startswith("")` 對每種語言都成立：

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

詢問 `code`（處理函式不認得的引數），它會回傳 `None`，SDK 會把它轉成空清單：

```python
result.completion.values  # []
```

`None` 的意思是「沒有建議」，永遠不是錯誤。UI 會退回一般的文字框。

## 一個你從沒宣告過的能力 {#a-capability-you-never-declared}

註冊處理函式本身就是宣告。連上用戶端看看：

```python
client.server_capabilities.completions  # CompletionsCapability()
```

你沒有在任何地方列出 `completions`。SDK 看到處理函式，就替你宣告了這項能力。每一項**可選**能力都是這樣運作的：處理函式就是宣告。（三個基本元件不是可選的：不管有沒有處理函式，`MCPServer` 一律會宣告它們。）

!!! check
    回到第一個 `server.py`（沒有處理函式的那個），照樣問它一次。呼叫會失敗，得到 JSON-RPC 錯誤：

    ```text
    Method not found
    ```

    而且 `client.server_capabilities.completions` 是 `None`。這正是能力的用意：行為良好的用戶端會先檢查它，絕不會送出你無法回答的請求。

## 相依的引數 {#dependent-arguments}

`github://repos/{owner}/{repo}` 有兩個參數，而 `repo` 的合理值取決於先選了哪個 `owner`。

這就是 `context` 的用途。它帶著使用者**已經解析完成**的引數：

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* 新的分支在範本的 `repo` 參數上觸發。
* `context.arguments` 是 `dict[str, str] | None`，存放目前已選的值（這裡是 `owner`）。
* 還沒有 `owner` 就沒有合理的建議，所以處理函式回傳 `None`。

用戶端用 `context_arguments=` 送出那些已解析的值。這次 `ref` 是 `ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`。以空的 `value` 詢問 `repo`，並傳入 `context_arguments={"owner": "modelcontextprotocol"}`：

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

拿掉 `context_arguments=`，同樣的呼叫會回傳 `[]`。處理函式在知道 owner 之前，沒辦法知道該建議哪些儲存庫。

!!! info
    `Completion` 也接受 `total=` 和 `has_more=`。當 `values` 只是更長清單的一部分時設定它們，UI 就能顯示「還有 200 個」。大多數處理函式用不到。

## 重點回顧 {#recap}

* 自動完成是給**提示詞引數**和**資源範本參數**的建議，僅此而已。
* `@mcp.completion()` 註冊那唯一的處理函式。它是 `async def (ref, argument, context) -> Completion | None`。
* 依 `isinstance(ref, ...)` 和 `argument.name` 分支。自己用 `argument.value` 過濾。
* `None` 會變成空清單，永遠不是錯誤。
* `context.arguments` 存放已解析的值；用戶端以 `context_arguments=` 提供它們。
* 一註冊處理函式，`completions` 能力就會出現。沒有它，請求會得到 `Method not found`。

建議是在使用者還在**填寫**提示詞或範本時幫忙；如果要在工具呼叫**進行到一半**時問使用者問題，要用的是 **[徵詢（elicitation）](../handlers/elicitation.md)**。工具除了文字之外還能回傳的所有東西，請見 **[圖片、音訊與圖示](media.md)**。
