---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

**MCP App** 是一個有門面的工具：除了資料之外，工具還會指向一份 HTML 文件，由 MCP 主機（host）把它繪製成可互動的介面。

兩個部分，永遠都是兩個部分：

1. **一個工具**，負責做事並回傳資料，跟任何其他工具一樣。
2. **一個 `ui://` 資源**，裡面裝著主機要為它顯示的 HTML。

工具帶有一個指向該資源的 `_meta.ui.resourceUri` 參照。主機用 `resources/read` 取得它，在**沙箱化的 iframe** 裡繪製，再透過 `postMessage` 把工具的結果推進那個 iframe。伺服器從頭到尾不會送出或收到任何 `ui/*` 訊息：那些流量是主機和 iframe 之間的事。你提供一個工具和一份 HTML 文件，場面由主機負責。

SDK 以內建的 `Apps` 擴充功能（`io.modelcontextprotocol/ui`）提供這項功能。如果還不熟悉[擴充功能](extensions.md)，先快速看過那一頁。一分鐘就好，看完再回來。

## 有錶面的時鐘 {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

四個動作：

* `Apps()`：一個實例容納所有綁定 UI 的工具和它們的資源。
* `@apps.tool(resource_uri="ui://clock/app.html")`：一個普通的工具，外加 `_meta.ui.resourceUri` 標記。`@mcp.tool()` 接受的所有東西（name、title、description……）都會原樣傳下去。
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`：對應的資源，以 `text/html;profile=mcp-app` 提供。正是這個 MIME 型別告訴主機「這是個 app，把它繪製出來」。
* `MCPServer("clock", extensions=[apps])`：選擇加入。伺服器現在會在 `capabilities.extensions` 底下宣告 `io.modelcontextprotocol/ui`。

HTML 本身會監聽主機的 `postMessage` 並顯示結果。真正的 app 請在 HTML 裡使用官方的 [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps) 瀏覽器 SDK。它提供 `ontoolresult`、`callServerTool`、`getHostContext` 和 `onhostcontextchanged`，不用自己處理原始的訊息事件。

## 優雅降級 {#graceful-degradation}

不是每個用戶端都會繪製 app。規格對這代表什麼講得很直白：

> Tools **MUST** return a meaningful `content` array even when UI is available.

模型讀的是 `content`；iframe 是給人看的。支援 UI 的主機照樣會把文字結果餵給模型，而純文字用戶端**只**會拿到那個。所以標準做法是一個工具，兩種答案。再看一次 `get_time`：

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

只有當用戶端宣告了 `io.modelcontextprotocol/ui` 擴充功能，**而且**在它的 `mimeTypes` 設定裡列出 `text/html;profile=mcp-app` 時，`client_supports_apps(ctx)` 才會是 `True`。這個欄位是必填的，所以省略它的用戶端不算數。同一個檔案裡的 `main()` 宣告的正是這些：協商的用戶端那一半，於是回來的是豐富版的答案。

!!! warning
    絕對不要把 `"[Rendered UI]"` 這類佔位文字當成唯一的內容回傳。如果後備文字沒有用，這個工具對每個純文字用戶端、對模型本身就都沒有用。好好寫那句話。

## 把 iframe 鎖緊 {#locking-the-iframe-down}

安全相關的中繼資料放在資源這一側：iframe 可以載入什麼、想要哪些瀏覽器權限、希望怎麼被嵌入：

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` 和 `permissions` 是**對主機的請求**，不是伺服器的行為。主機用它們建構 iframe 的 Content-Security-Policy 和 Permissions-Policy，而且可能拒絕。在 JS 裡做功能偵測，不要假設一定會獲准。

`ResourceCsp` 逐欄位說明（Python 名稱、線路上的鍵、主機拿它做什麼）：

| Python | 線路（`_meta.ui.csp`） | 控制 |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`：`fetch`/XHR 可以連去哪裡 |
| `resource_domains` | `resourceDomains` | `img-src`、`style-src`……：靜態資產 |
| `frame_domains` | `frameDomains` | `frame-src`：巢狀 iframe |
| `base_uri_domains` | `baseUriDomains` | `base-uri`：`<base>` 可以指向哪裡 |

`ResourcePermissions`：每個欄位替 iframe 請求一項瀏覽器權限。

| Python | 線路（`_meta.ui.permissions`） |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP 和權限放在**資源**上，永遠不放在工具上。規格的工具中繼資料沒有它們的位置，放在那裡主機也會忽略。SDK 讓這個錯誤根本寫不出來：`@apps.tool()` 就是沒有 `csp` 參數。

### 可見性 {#visibility}

工具上的 `visibility=["app"]` 表示「這是為 iframe 存在的，不是為模型」：

* `"model"`：模型可以呼叫它。
* `"app"`：iframe 可以呼叫它（透過 `callServerTool`）。
* 省略：兩者皆可，這是預設值。

過濾是**主機**的工作。伺服器在 `tools/list` 裡照常列出僅限 app 的工具；主機負責對模型隱藏它們。不要在伺服器端過濾。

## SDK 強制執行的規則 {#the-rules-the-sdk-enforces}

這些全都在啟動時就失敗，不會等到上線：

* `resource_uri` 或資源 URI 不是 `ui://...`，會在裝飾／註冊時引發 `ValueError`。
* 工具綁定到一個**沒有對應已註冊資源**的 URI，會在 `MCPServer(extensions=[apps])` 取用這個擴充功能時引發 `ValueError`。一個宣稱有 HTML、`resources/read` 卻 404 的工具是設定錯誤，所以它拒絕建構。
* `@apps.tool()` 上的 `meta={"ui": ...}` 是 `ValueError`。`_meta["ui"]` 歸裝飾器管；要表達請用 `resource_uri=` 和 `visibility=`。其他的 `meta=` 鍵可以正常一起合併。

目前 TypeScript 的 ext-apps SDK 和 FastMCP 都不會攔下這些；我們寧可讓你比主機早一步發現。

## 不只是行內 HTML {#beyond-inline-html}

`add_html_resource` 涵蓋常見情況：一段 HTML 字串。其他情況，像是磁碟上的 HTML 或動態產生的內容，就自己建立資源再交出去：

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

資源沒有明確設定 MIME 型別時，`add_resource` 會補上 `text/html;profile=mcp-app`；明確設定卻不相符的則會拒絕：掛在任何其他 MIME 型別底下的 `ui://` 資源，沒有任何主機會繪製。

!!! tip
    目標是某個 GA 前的主機，還在讀已棄用的扁平 `_meta["ui/resourceUri"]` 鍵？自己合併進去：`@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`。巢狀的 `ui` 物件才是規格的形狀；扁平鍵正在退場。

## 看它跑起來 {#see-it-run}

`examples/stories/` 裡的 `apps` 故事就是這一頁的可執行版本，成對出現：一個帶有綁定 UI 時鐘工具的伺服器，以及一個會協商 Apps、讀取工具的 `_meta.ui.resourceUri`、取得 HTML 並呼叫工具的用戶端。

```bash
uv run python -m stories.apps.client
```
