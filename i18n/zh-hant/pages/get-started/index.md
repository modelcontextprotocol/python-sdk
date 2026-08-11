---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# 開始使用 {#get-started}

剛接觸 MCP，或剛接觸這個 SDK？從這裡開始。這幾頁會帶你從零開始，做出一個能運作、經過測試的伺服器：[安裝 SDK](installation.md)、建立[第一個伺服器](first-steps.md)、[把它接上真正的 MCP 主機（host）](real-host.md)，再用記憶體內用戶端[測試它](testing.md)。

## 執行程式碼 {#run-the-code}

所有程式碼區塊都可以直接複製使用：每一個都是完整、可運作的檔案。

想跟著做的話，把程式碼區塊貼進 `server.py`，然後用 MCP Inspector 開啟：

```console
uv run mcp dev server.py
```

**強烈建議**自己寫下（或複製）程式碼、動手修改，並在本機執行。在自己的編輯器裡用過，才真正看得出重點在哪：要寫的東西有多少、自動完成的體驗，以及型別檢查在執行之前就幫你抓出錯誤。

## 不需要猜 {#you-will-not-be-guessing}

這份說明文件裡的每個範例，都是 SDK 自己的儲存庫中 [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) 底下的完整檔案，而且每一個都由 SDK 的測試套件透過**記憶體內用戶端**實際跑過：

```python
import pytest
from mcp import Client

from server import mcp


@pytest.mark.anyio
async def test_add() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("add", {"a": 1, "b": 2})
        assert result.structured_content == {"result": 3}
```

沒有子處理程序、沒有連接埠、沒有傳輸方式。`Client(mcp)` 直接連到伺服器物件。

如果 SDK 的某個改動弄壞了這幾頁上的範例，CI 會比頁面先亮紅燈。你在這裡讀到的程式碼，就是實際執行的程式碼。

在[測試](testing.md)那一頁你會自己用到這個做法；測試自己的伺服器時也是這樣做。

## 接下來往哪裡走 {#where-to-go-next}

伺服器跑起來之後，這份說明文件的其他部分是參考資料，不是課程。每一頁都可以獨立閱讀，直接跳到需要的地方即可：

* 伺服器對外提供什麼（工具、資源、提示詞），請見 **[伺服器](../servers/index.md)**。
* 註冊的函式裡有哪些東西可用，請見 **[在處理函式內部](../handlers/index.md)**。
* 怎麼把伺服器交到用戶端面前（stdio、HTTP、現有的 FastAPI 應用程式），請見 **[執行伺服器](../run/index.md)**。
* 打造另一端，也就是**使用** MCP 伺服器的應用程式，請見 **[用戶端](../client/index.md)**。
