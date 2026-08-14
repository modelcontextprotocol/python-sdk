---
translation:
  sections: [496394d24d221bf1, 4ceb4591180dc6c3, 0fd63e4682d02e0c, 969ede0bd3686a16, 043f526230dd243d, 6ee3e9bcfd24047a]
  tool: 1
---
# 媒體 {#media}

工具能回傳的不只是文字。

SDK 內建兩個處理二進位結果的輔助工具（**`Image`** 和 **`Audio`**），以及一個 **`Icon`** 型別，讓伺服器、工具、資源和提示詞在用戶端的 UI 裡有張臉。

## 回傳圖片 {#returning-an-image}

把回傳型別註記為 `Image`，指向一個檔案，然後回傳它：

```python title="server.py" hl_lines="8 12 14"
--8<-- "docs_src/media/tutorial001.py"
```

* `Image` 只接受 `path`（要讀取的檔案）或 `data`（原始位元組）其中之一。
* 用戶端看到的 MIME 型別是從副檔名猜出來的：`logo.png` 會宣告為 `image/png`。
* 這裡跟 logo 沒有特別關係。`server.py` 旁邊的任何 PNG 都行：程式碼繪製的圖表、示意圖、照片都可以。

`Image` 是 SDK 提供的便利工具，不是協定型別。實際傳輸時，回傳值會變成一個 **`ImageContent`** 區塊（檔案的位元組經 base64 編碼，加上 MIME 型別）：

```python
result.content             # [ImageContent(type="image", data="iVBORw0KGgoAAAANSUhEUg...", mime_type="image/png")]
result.structured_content  # None
```

有兩點值得注意：

* `data` 是 base64。你完全沒碰過位元組；SDK 讀了檔案並完成編碼。
* `structured_content` 是 `None`。`Image` 是給模型看的內容，不是給應用程式解析的資料：沒有輸出 schema。（對照 **[結構化輸出](structured-output.md)**，那裡的回傳註記**就是** schema。）

!!! info
    `ImageContent` 和 `AudioContent` 位於 `mcp.types`，就在普通 `str` 結果會變成的 `TextContent` 旁邊（**[工具](tools.md)**）。工具結果是一串內容區塊的清單；`Image` 和 `Audio` 是產生這兩種二進位區塊最簡短的方式。

### 試試看 {#try-it}

把任何一張 PNG 放在 `server.py` 旁邊，命名為 `logo.png`，然後執行：

```console
uv run mcp dev server.py
```

打開 **Tools** 分頁並呼叫 `logo`。結果不是字串：它是一個 `image` 內容區塊，Inspector 會把圖片顯示出來。從磁碟上的檔案到螢幕上的像素，中間的一切都是 SDK 做的。

## 回傳音訊 {#returning-audio}

`Audio` 的形式一模一樣。`logo.png` 留在原位，再放一個 WAV 在旁邊，命名為 `chime.wav`：

```python title="server.py" hl_lines="18-21"
--8<-- "docs_src/media/tutorial002.py"
```

結果是一個 **`AudioContent`** 區塊：

```python
result.content             # [AudioContent(type="audio", data="UklGR...", mime_type="audio/wav")]
result.structured_content  # None
```

同樣的道理：磁碟上的檔案進去，base64 和 MIME 型別出來，沒有輸出 schema。

## 位元組或檔案 {#bytes-or-a-file}

兩個輔助工具也都接受 `data=`（原始位元組）來取代 `path=`。這是給那些本來就不是來自檔案的位元組用的模式，例如資料庫欄位、HTTP 回應，或 Pillow 剛畫好的東西：

```python title="server.py" hl_lines="14 15"
--8<-- "docs_src/media/tutorial003.py"
```

用 `path=` 時什麼都不用宣告：建立結果時才讀取檔案，MIME 型別從副檔名猜出來：

* `Image`：`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`。
* `Audio`：`.wav`、`.mp3`、`.ogg`、`.flac`、`.aac`、`.m4a`。

認不出來的副檔名會退回 `application/octet-stream`。

!!! check
    用 `data=` 時沒有檔名，也就沒有東西可以猜。忘了 `format=`，SDK 就會退回預設值：圖片是 `image/png`，音訊是 `audio/wav`。這樣用 MP3 位元組建立 `Audio`，用戶端會被告知 `mime_type="audio/wav"`，然後老老實實地解碼失敗。傳 `data=` 的時候，就一起傳 `format=`。

## 圖示 {#icons}

`Icon` 是中繼資料，不是內容。它不帶圖片本身，而是用一個 URI 指向圖片；用戶端可以去抓取並顯示在伺服器名稱、工具、資源或提示詞旁邊。

```python title="server.py" hl_lines="4-5 7 10 16"
--8<-- "docs_src/media/tutorial004.py"
```

* `src` 是用戶端能解析的 URI：`https:`，或是想把圖示直接內嵌、省掉額外抓取的話，用 `data:` URI。
* `mime_type` 和 `sizes`（`"48x48"`，可縮放格式則用 `"any"`）讓用戶端在你提供多個圖示時挑出合適的那一個。
* `theme="light"` 或 `theme="dark"` 標記圖示適用於哪一種配色。

同樣的 `icons=[...]` 關鍵字在 `MCPServer(...)`、`@mcp.tool()`、`@mcp.resource()` 和 `@mcp.prompt()` 都能用。

### 用戶端在哪裡看到它們 {#where-a-client-sees-them}

圖示會跟著它所裝飾的東西一起傳送。伺服器的圖示在用戶端連線時送達，放在 `client.server_info` 上（在 2026 世代的連線上是選用的，所以先做型別收窄）：

```python
assert client.server_info is not None  # python-sdk servers identify themselves by default
client.server_info.icons  # [Icon(src="https://example.com/brand-kit.png", mime_type="image/png", sizes=["48x48"])]
```

工具的圖示在 `tools/list` 回傳的 `Tool` 物件上，資源的在 `resources/list` 的 `Resource` 上，提示詞的在 `prompts/list` 的 `Prompt` 上。欄位一律叫做 `icons`。

## 重點回顧 {#recap}

* 從工具回傳 `Image` 或 `Audio`，用戶端就會收到一個 `ImageContent`／`AudioContent` 區塊：位元組經 base64 編碼，附上 MIME 型別。
* 可以用 `path=` 建立並讓副檔名決定 MIME 型別，或用記憶體內的 `data=` 加上明確的 `format=`。
* 媒體結果沒有 `structured_content`，也沒有輸出 schema。
* `Icon` 是個指標：一個 `src` URI，加上選用的 `mime_type`、`sizes` 和 `theme`。
* `icons=[...]` 在伺服器、工具、資源和提示詞上都能用，用戶端會在對應的物件上找到它們。

以上就是工具能放**進**結果裡的全部東西。工具**失敗**時會發生什麼事（以及誰該知道），請見 **[處理錯誤](handling-errors.md)**。
