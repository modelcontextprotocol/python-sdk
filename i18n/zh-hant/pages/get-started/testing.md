---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# 測試 {#testing}

Python SDK 附帶一個 `Client` 類別，內建**記憶體內傳輸**：把伺服器物件傳給它，它就會直接連上去。

沒有子處理程序，沒有連接埠，根本沒有傳輸層。概念和 FastAPI 的 `TestClient` 一樣。

## 基本用法 {#basic-usage}

假設有一個簡單的伺服器，只有一個工具：

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

要執行下面的測試，需要兩個額外的（開發用）相依套件：

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    這份說明文件假設你已經會用 [`pytest`](https://docs.pytest.org/en/stable/)。

    下面的測試用 [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) 來在一行內對整個結果物件做斷言。它會把測試的輸出記錄成你看到的 `snapshot(...)` 字面值。如果不想用它，拿掉 import，像其他測試一樣對你在意的欄位做斷言（`result.content[0].text == "3"`）即可。

接著是測試：

```python title="test_server.py"
import pytest
from inline_snapshot import snapshot
from mcp import Client
from mcp.types import CallToolResult, TextContent

from server import mcp


@pytest.fixture
def anyio_backend():  # (1)!
    return "asyncio"


@pytest.fixture
async def client():  # (2)!
    async with Client(mcp, raise_exceptions=True) as c:
        yield c


@pytest.mark.anyio
async def test_call_add_tool(client: Client):
    result = await client.call_tool("add", {"a": 1, "b": 2})
    # Drop the server identity stamp in `_meta`; it is not what this test is about.
    result.meta = None
    assert result == snapshot(
        CallToolResult(
            content=[TextContent(type="text", text="3")],
            structured_content={"result": 3},
        )
    )
```

1. 如果用的是 `trio`，改成回傳 `"trio"`。細節請見 [anyio 說明文件](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on)。
2. 這個 fixture 會 yield 一個已連線的用戶端。每個接收 `client` 的測試都會拿到一條連到同一個伺服器的全新記憶體內連線。

這樣就完成了！現在可以擴充測試，涵蓋更多情境。

## 為什麼要 `raise_exceptions=True`？ {#why-raise_exceptionstrue}

可能出錯的地方有兩種，而這個旗標只影響其中一種。

**你的工具**內部引發的例外不算協定失敗。它會變成一個帶有 `is_error=True` 的正常結果，模型會讀到那則訊息。`raise_exceptions` 不會改變這一點：不管有沒有設定，`call_tool` 都回傳同樣的 `is_error=True` 結果。這部分有一整頁的說明：**[處理錯誤](../servers/handling-errors.md)**。

發生在工具本體**之外**的失敗就不一樣了。在 `Client(mcp)` 給你的連線上，伺服器會先把它淨化成通用的 `"Internal server error"`，用戶端才看得到。意外當掉的細節本來就不該洩漏給遠端呼叫端。但在測試裡，這正是你**不**想要的，也正是 `raise_exceptions=True` 改變的地方：測試會看到真正的訊息，而不是淨化過的版本。

測試裡就開著它。在正式環境的程式碼裡它沒有任何意義。

## 預設為處理程序內連線 {#in-process-by-default}

!!! note
    `Client(mcp)` 以處理程序內的方式連線，而且預設是**世代中立**的：它會探測伺服器，選出合適的協定路徑。如果測試要驗證舊版特有的語意（取樣（sampling）或徵詢（elicitation）的推送、`message_handler`），就固定用 `mode="legacy"`，並且在那裡拿掉 `raise_exceptions=True`：舊版連線本來就不會淨化，而這個旗標會讓失敗在伺服器任務裡重新引發，而不是在你的測試裡。

也正是因為這一行，這份說明文件才敢保證範例都能跑：每個範例檔案都由 SDK 自己的測試套件實際執行過，幾乎全部都是透過這個用戶端。你用的工具和 SDK 用在自己身上的是同一個。

現在有了一個可以運作、也測試過的伺服器。要把它放進真正的應用程式（Claude Desktop、IDE）裡，請見 **[連接真實的主機（host）](real-host.md)**；其他所有提供服務的方式請見 **[執行伺服器](../run/index.md)**。
