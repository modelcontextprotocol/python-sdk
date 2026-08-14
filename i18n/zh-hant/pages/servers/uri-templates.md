---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# URI 範本與路徑安全 {#uri-templates-and-path-safety}

這一頁是參考文件，涵蓋 [`@mcp.resource`](resources.md) 接受的 URI 範本語法，以及 SDK 套用在擷取值上的路徑安全策略。想先了解資源是什麼、什麼時候該用，請從 **[資源](resources.md)** 開始；這一頁假設你已經能自在地宣告資源，想要的是完整的運算子集合、安全相關的設定選項，或低階的接線方式。

範本語法是 [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)。SDK 支援其中一個子集，挑選的依據是用來比對傳入的 `resources/read` URI，另外再加上一層安全機制，會拒絕解析後落在預定服務目錄之外的值。協定層級的細節（訊息格式、生命週期、分頁）請見 [MCP 資源規格](https://modelcontextprotocol.io/specification/latest/server/resources)。

## 完整的運算子集合 {#the-full-operator-set}

最基本的佔位符 `{user_id}` 是 **[資源](resources.md)** 介紹過的那一種。另外還有四種運算子形式；下面把它們放在同一個伺服器上，方便並排比較：

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

每個標示出來的裝飾器都是切分 URI 的不同方式。以下各節從上到下逐一說明。

### 簡單展開：`{name}` {#simple-expansion-name}

`books://{isbn}` 是最平常的基本形式。佔位符對應到 `isbn` 參數，所以用戶端讀取 `books://978-0441172719` 時會呼叫 `get_book("978-0441172719")`。

單純的 `{name}` 遇到第一個 `/` 就停。`books://978/extra` 不會比對成功，因為 `978` 後面的斜線結束了擷取，剩下 `/extra` 沒有去處。

### 型別轉換 {#type-conversion}

擷取出來的值一開始都是字串，但可以宣告更明確的型別，SDK 會幫忙轉換。`orders://{order_id}` 對應的函式參數是 `order_id: int`，所以讀取 `orders://12345` 會呼叫 `get_order(12345)`，而不是 `get_order("12345")`。處理函式直接拿它做算術（`order_id + 1`），不必轉型。

### 多段路徑：`{+name}` {#multi-segment-paths-name}

要擷取含有斜線的值，用 `{+name}`。以 `manuals://{+path}` 為例：

* `manuals://returns.md` 得到 `path = "returns.md"`
* `manuals://printing/setup.md` 得到 `path = "printing/setup.md"`

只要值是階層式的，就用 `{+name}`：檔案系統路徑、巢狀物件的鍵、代理轉發的 URL 路徑。

### 查詢參數：`{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` 把 `limit` 和 `sort` 放在 `?` 後面。路徑指出是**哪一本**書；查詢則調整**怎麼**讀它。

查詢參數採寬鬆比對：順序無所謂，多出來的會被忽略，省略的參數則落回函式的預設值。所以 `reviews://978-0441172719` 會用 `limit=10, sort="newest"`，而 `reviews://978-0441172719?sort=top` 只覆寫 `sort`。

### 路徑段轉成清單：`{/name*}` {#path-segments-as-a-list-name}

如果希望每個路徑段各自成為清單中的一個項目，而不是一個帶斜線的字串，用 `{/name*}`。以 `shelves://browse{/path*}` 為例，用戶端讀取 `shelves://browse/fiction/sci-fi` 會呼叫 `browse_shelf(["fiction", "sci-fi"])`。

### 範本速查 {#template-reference}

最常見的樣式：

| 樣式         | 範例輸入              | 得到                    |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | **不相符**（停在 `/`） |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### 剖析器會拒絕什麼 {#what-the-parser-rejects}

有幾種範本寫法會在一開始就被擋下來，而不是等到第一個請求才失敗。`@mcp.resource` 在裝飾器執行時就剖析範本，所以這些情況都不會進到執行中的伺服器。

`UriTemplate.parse()` 在下列情況會引發 `InvalidUriTemplate`：

* **兩個變數之間沒有任何東西。** `manuals://{+path}{ext}` 會被拒絕：比對時無法判斷 `path` 在哪裡結束、`ext` 從哪裡開始。在它們之間放一個字面字元（`manuals://{+path}/{ext}`），或改用自帶分隔符號的運算子。`manuals://{+path}{.ext}` 可以接受，因為 `{.ext}` 自己提供了 `.`。
* **超過一個多段變數。** 每個範本最多只能有一個 `{+var}`、`{#var}` 或展開變數（`{/var*}`、`{.var*}`、`{;var*}`）。兩個就先天有歧義：沒有合理的依據決定哪一個該吸收多出來的段。
* **一般的語法錯誤**：沒關上的大括號、重複使用的變數名稱，或 SDK 不支援的 RFC 6570 功能，例如 `{var:3}` 前綴修飾詞或 `{?vars*}` 查詢展開。

除此之外，當處理函式的某個參數綁定到範本尾端 `{?...}`/`{&...}` 區段裡的查詢變數，卻沒有 Python 預設值時，`@mcp.resource` 會引發 `ValueError`。這些變數是寬鬆比對的（用戶端可以省略其中任何一個），所以沒有預設值的參數只會在第一個省略它的請求上，以一個看不出原因的內部錯誤浮現。上面伺服器裡的 `reviews://{isbn}{?limit,sort}` 就是寫對的版本：`limit` 和 `sort` 都有預設值。

## 安全性 {#security}

範本參數來自用戶端。如果未經檢查就流入檔案系統或資料庫操作，像 `../../etc/passwd` 這樣的值可能會解析到預定服務目錄之外。

### SDK 預設檢查什麼 {#what-the-sdk-checks-by-default}

在處理函式執行之前，SDK 會拒絕任何符合下列條件的參數：

* 透過 `..` 元件跳出起始目錄
* 看起來像絕對路徑（`/etc/passwd`、`C:\Windows`）或 Windows 磁碟機相對路徑（`C:foo`）。磁碟機相對路徑的值和 `x:y` 這類帶命名空間的識別碼，從字串上無法區分，所以任何「單一字母加冒號」的值預設都會被拒絕；如果該參數確實會合法地收到這種值，就把它設為豁免
* 含有 null 位元組（`\x00`）

`..` 的檢查是以路徑元件為單位，不是子字串掃描。`v1.0..v2.0` 或 `HEAD~3..HEAD` 這類值會通過，因為其中的 `..` 並不是獨立的路徑段。

這些檢查套用在解碼後的值上，所以不管在 URI 裡怎麼編碼，都抓得到路徑穿越（`../etc`、`..%2Fetc`、`%2E%2E/etc`、`..%5Cetc`、`%00` 全都會被攔下）。

!!! check
    從上面的伺服器讀取 `manuals://../etc/passwd`，請求會直接被拒絕：範本比對在第一次失敗時就停止，所以不會退而嘗試後面（可能更寬鬆）的範本。用戶端看到的是和完全不符合任何範本的 URI 一樣的 `-32602`「Unknown resource」錯誤，而 `read_manual` 根本不會執行。

### 檔案系統處理函式：使用 safe_join {#filesystem-handlers-use-safe_join}

內建檢查擋得住常見情況，但無從得知你的沙箱邊界。存取檔案系統時，用 `safe_join` 解析路徑，並確認它仍在基底目錄之內：

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` 抓得到符號連結跳脫、`..` 序列，以及簡單字串檢查會漏掉的絕對路徑伎倆。如果解析後的路徑跳出 `DOCS_ROOT`，它會引發 `PathEscapeError`，在用戶端會以 `ResourceError` 的形式呈現。

### 預設值礙事的時候 {#when-the-defaults-get-in-the-way}

有時候這些檢查會擋掉合法的值。目錄匯入工具可能就是要接收絕對路徑，或者某個參數是像 `../sibling` 這樣的相對參照，處理函式會安全地解讀它而不碰檔案系統。把那個參數設為豁免，或放寬整個伺服器的策略：

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* 裝飾器上的 `security=ResourceSecurity(exempt_params={"source"})` 只對那一個資源的那一個參數跳過檢查。伺服器其餘部分維持預設策略。
* `MCPServer` 建構子上的 `resource_security=` 設定所有資源的預設值。這裡的 `relaxed` 把 `..` 檢查整個關掉。

可設定的檢查：

| 設定                    | 預設值  | 作用                                |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | 拒絕跳出起始目錄的 `..` 序列 |
| `reject_absolute_paths` | `True`  | 拒絕 `/foo`、`C:\foo`、UNC 路徑和磁碟機相對的 `C:foo`（也會抓到 `x:y`） |
| `reject_null_bytes`     | `True`  | 拒絕含有 `\x00` 的值    |
| `exempt_params`         | 空      | 要跳過檢查的參數名稱  |

這些檢查只是啟發式的前置過濾；存取檔案系統時，`safe_join` 仍然是真正的隔離邊界。

!!! tip
    如果處理函式無法完成請求（檔案不存在、id 不認識），就引發例外。SDK 會把它轉成錯誤回應。協定錯誤和工具錯誤的差別請見 **[處理錯誤](handling-errors.md)**。

## 低階 Server 上的資源 {#resources-on-the-low-level-server}

如果是在低階 `Server` 上開發（見 **[低階 Server](../advanced/low-level-server.md)**），就直接為 `resources/list` 和 `resources/read` 這兩個協定方法註冊處理函式。沒有裝飾器；協定型別要自己回傳。

### 靜態資源 {#static-resources}

固定的 URI 就維護一份登錄表，依完全相符來分派：

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

list 處理函式告訴用戶端有哪些可用；read 處理函式提供內容。先查登錄表，如果有範本（見下）就接著落到範本，其餘一律引發例外。

### 範本 {#templates}

`MCPServer` 用的範本引擎位於 `mcp.shared.uri_template`，可以獨立使用。剖析和比對完全一樣；路由和安全策略要自己接線。

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

標示出來的幾行做了三件事：

* **剖析一次，每個請求比對一次。** `UriTemplate.parse()` 建立範本；`template.match(uri)` 以 `dict` 回傳擷取出的變數，URI 不符則回傳 `None`。URL 解碼在 `match()` 內部進行；解碼後的值原樣回傳，不做路徑安全驗證。出來的值都是字串：自己轉換（`int(matched["id"])`、`Path(matched["path"])`）。
* **自己套用安全檢查。** `MCPServer` 預設執行的 `..` 和絕對路徑檢查位於 `mcp.shared.path_security`。`read_manual_safely` 在碰 `MANUALS` 之前會先呼叫它們。如果某個參數不是檔案系統路徑（ISBN、搜尋查詢），就跳過那個值的檢查：策略是逐個處理函式控制，而不是透過設定物件。
* **從同一個來源列出範本。** 用戶端透過 `resources/templates/list` 探索範本。`str(template)` 會還原出原本的範本字串，所以清單和比對器共用同一個事實來源。

## 重點回顧 {#recap}

* `{name}` 比對一段；`{+name}` 保留斜線；`{?a,b}` 從查詢字串取值；`{/name*}` 把各段拆成清單。
* 兩個變數之間沒有任何東西，或出現第二個多段變數，都會在剖析時被拒絕。綁定到尾端 `{?...}`/`{&...}` 查詢變數的參數必須宣告 Python 預設值。
* 替參數加上註記（`order_id: int`），SDK 就會轉換。
* 預設的安全策略會在處理函式執行前拒絕 `..`、絕對路徑和 null 位元組；用 `security=ResourceSecurity(...)` 針對個別資源覆寫，或用 `resource_security=` 套用到整個伺服器。
* 存取檔案系統時，`safe_join` 是隔離邊界。
* 在低階 `Server` 上，用 `UriTemplate.parse()` 剖析、用 `.match()` 比對，並自己套用 `mcp.shared.path_security`。
