---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# 標頭參數 {#header-parameters}

大多數伺服器都用不到這項功能。

伺服器前面的閘道或負載平衡器，只能根據不必解析主體就讀得到的內容來路由。用 `x-mcp-header` 標記某個工具引數，使用 `2026-07-28` **[協定版本](../protocol-versions.md)** 的用戶端就會把它的值也當成 HTTP 標頭送出。

## 標記引數 {#mark-an-argument}

這個標記就是引數的 JSON Schema 裡多出的一個鍵。在 `MCPServer` 上，由 `Field` 把它放進去：

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* 在 `2026-07-28` 的 Streamable HTTP 上，用戶端會連同主體一起送出 `Mcp-Param-Region`；兩者不一致時，伺服器會拒絕這次呼叫。
* 還沒列出過工具的用戶端從沒看過這個標記：它不會送出標頭，伺服器就會拒絕這次呼叫。這時本 SDK 的 `Client` 會列出工具並重送一次呼叫，所以先列出工具只是省下一次往返。
* 其他連線都會忽略這個註記。

函式不用改：`region` 仍然以引數的形式傳入。

## 哪些引數可以標記 {#what-can-be-marked}

`str`、`int` 和 `bool` 引數。其他型別在註冊工具時就會遭到拒絕，並引發 `InvalidSignature`。

這也包括 `str | None`，因為它沒有單一型別。選用引數需要用 Pydantic 的 `WithJsonSchema` 把 schema 明確寫出來：

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## 在低階 `Server` 上 {#on-the-low-level-server}

在那裡 `input_schema` 是手寫的，所以直接把這個鍵寫進去：

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* 沒有任何機制會替你檢查註記：無效的註記會照樣送出，而 `2026-07-28` 用戶端會把這個工具排除在清單之外。

### 依名稱取得 schema {#schemas-by-name}

要檢查標頭，SDK 必須在分派呼叫之前拿到工具的輸入 schema。沒有 `get_tool_input_schema` 時，只要呼叫帶有引數，SDK 每次都會執行 `on_list_tools` 處理函式來取得 schema，不論有沒有任何工具帶有標記。

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* 傳入這個函式，就能用手邊已有的資料來回答。
* 工具沒有需要檢查的內容時，回傳 `None`。

## 重點回顧 {#recap}

* 在工具引數上加 `x-mcp-header`，`2026-07-28` 用戶端就會把它再以 `Mcp-Param-*` HTTP 標頭送一次。
* 標頭與主體不一致的呼叫，伺服器會拒絕。
* 只有 `str`、`int` 和 `bool` 引數可以標記。其他型別 `MCPServer` 會引發 `InvalidSignature`。
* 低階 `Server` 什麼都不檢查，而用戶端會捨棄註記無效的工具。
* 有了 `get_tool_input_schema`，低階 `Server` 就不必在每次呼叫時執行 `on_list_tools`。

手寫 `Server` API 的其餘部分請見 **[低階 Server](low-level-server.md)**。
