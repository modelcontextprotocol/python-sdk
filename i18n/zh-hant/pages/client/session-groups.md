---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# 工作階段群組 {#session-groups}

一個 `Client` 只連到一台伺服器。實際的應用程式往往需要好幾台（搜尋伺服器、資料庫伺服器、內部 API），結果得替每一台各自管理一條連線和一份工具清單。

**`ClientSessionGroup`** 是單一物件，裡面握有多條連線，並把它們公開的所有東西合併成一個統一的檢視。

## 兩台伺服器 {#two-servers}

先從兩台普通的伺服器開始。它們彼此毫無關係，所以很自然地都把自己的工具取名為 `search`：

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## 一個群組 {#one-group}

建立一個 `ClientSessionGroup`，然後對每台伺服器各呼叫一次 **`connect_to_server`**：

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` 接受的是傳輸參數，不是伺服器物件：用 `StdioServerParameters`（來自 `mcp`）啟動子處理程序，或用 `StreamableHttpParameters` / `SseServerParameters`（來自 `mcp.client.session_group`）連到已經在某個 URL 上監聽的伺服器。
* `group.tools` 是一個 `dict[str, Tool]`，收集所有已連線伺服器的工具。`group.resources` 和 `group.prompts` 的結構相同。
* `group.call_tool(name, arguments)` 會查詢名稱、找出擁有它的工作階段（session），再把呼叫轉送過去。你永遠不需要指明是哪台伺服器。

!!! check
    把 `client.py` 放在兩台伺服器旁邊執行。第二次 `connect_to_server` 會拒絕：

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    這是一個 `MCPError`，在第二台伺服器的任何東西被登記之前就引發了。名稱在**整個**群組內必須唯一，而兩台你無法掌控的伺服器遲早會撞名。

## `component_name_hook` {#component_name_hook}

這個問題要在群組這邊解決，而不是在伺服器端。傳入一個接收 `(name, server_info)` 的函式，群組會對它登記的每個名稱執行這個函式：

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

再執行一次。`print(sorted(group.tools))` 現在兩個都會顯示：

```text
['Library.search', 'Web.search']
```

* **鍵**是你自己決定的。`by_server` 用 `server_info.name` 組出來，也就是每個 `MCPServer(...)` 建構時傳入的名稱。
* 裡面的 `Tool` 完全沒動：`group.tools["Web.search"].name` 仍然是 `"search"`，而這也是 `call_tool` 放上線路的名稱。前綴永遠不會離開你的處理程序。
* 不只工具如此。圖書館的 `hours` 資源登記為 `Library.hours`。

!!! tip
    這個 hook 會對**每台**伺服器的**每個**名稱執行，不只在衝突時才執行：沒有所謂「撞名才加前綴」的模式。選定一套命名規則，讓它套用到所有地方。

## 新增與移除伺服器 {#adding-and-removing-servers}

`connect_to_server` 會回傳它開啟的 `ClientSession`。如果之後可能想拿掉那台伺服器，就把它留著：`await group.disconnect_from_server(session)` 會把它的工具、資源和提示詞從群組中移除。

如果手上已經有一個連線中的 `ClientSession`（`Client.session` 就是一個），改把它交給 `await group.connect_with_session(server_info, session)`，不必另開新的傳輸。它彙整的方式相同。群組永遠不會關閉不是它自己開啟的工作階段。`server_info` 用來替伺服器命名，供元件前綴使用；在 2026 世代的連線上，`client.server_info` 可能是 `None`（身分是選填的），這種情況下就傳入你自己的 `Implementation(name=..., version=...)`。

## 傳統的交握 {#the-classic-handshake}

`ClientSessionGroup` 建立在 `ClientSession` 之上，而不是 `Client`。每次 `connect_to_server` 都會執行傳統的 `initialize` 交握，從不送出 **[協定版本](../protocol-versions.md)** 裡描述的 `server/discover` 探測。每台 MCP 伺服器都懂這套交握，所以這不會讓你犧牲任何相容性；只是代表群組面對一台本來能做得更好的伺服器時，走的是比較舊、比較慢的路徑。

## 重點回顧 {#recap}

* `ClientSessionGroup` 握有多條伺服器連線，並把它們的工具、資源和提示詞各自合併成一個 `dict`。
* 每台伺服器呼叫一次 `connect_to_server(params)`。它接受傳輸參數，絕不是 `Client` 接受的伺服器物件或 URL。
* `group.call_tool(name, arguments)` 會替你轉送到擁有該工具的伺服器。
* 名稱在整個群組內必須唯一；兩台都有 `search` 工具的伺服器無法原樣共存。
* `component_name_hook=` 會改寫每個登記的名稱。dict 的鍵會變，線路上的名稱不變。
* `connect_with_session` 加入你已經握有的工作階段；`disconnect_from_server` 移除一個。

群組使用的交握（以及 `Client` 偏好的那套更快的交握）是 **[協定版本](../protocol-versions.md)** 的主題。
