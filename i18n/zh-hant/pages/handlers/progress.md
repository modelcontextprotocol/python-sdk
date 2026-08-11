---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# 進度 {#progress}

一個要跑三十秒、而這三十秒內毫無動靜的工具，看起來就像壞了。

**進度通知**就是用來解決這件事。工具回報自己做到哪裡；用戶端決定拿它畫什麼：進度條、轉圈圈的圖示，或一行記錄。

## 從工具回報 {#report-it-from-the-tool}

接收一個 **`Context`** 參數，然後呼叫 `report_progress`：

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

三個引數，意義由你決定：

* `progress`：做到哪裡了。規格要求它每次回報都要**遞增**；不要重複同一個值，也不要倒退。
* `total`：總共有多少，如果知道的話。可省略。
* `message`：描述**這一步**的一行人類可讀文字。可省略。

`ctx` 是因為型別提示而被注入的，模型永遠看不到它：`import_catalog` 的輸入 schema 只有一個屬性，`urls`。**[Context](context.md)** 那一頁專門講這個物件；進度只是它提供的功能之一。

## 從用戶端監聽 {#listen-for-it-from-the-client}

用戶端是**逐次呼叫**選擇加入的，做法是把 `progress_callback=` 傳給 `call_tool`：

```python title="client.py" hl_lines="7 16"
import anyio
from mcp import Client

from server import mcp


async def show(progress: float, total: float | None, message: str | None) -> None:
    print(f"{message} ({progress}/{total})")


async def main() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "import_catalog",
            {"urls": ["https://example.com/a.json", "https://example.com/b.json"]},
            progress_callback=show,
        )
    print(result.structured_content)


anyio.run(main)
```

回呼是一個 `async` 函式，接收的正是伺服器回報的內容：`progress`、`total`、`message`。

!!! info
    `Client(mcp)` 在記憶體內直接連上伺服器物件，和 **[測試](../get-started/testing.md)** 那一頁用的是同一個用戶端。不管 `Client` 用哪種傳輸方式，`progress_callback` 都是同一個參數；接下來看到的**時序**則是記憶體內連線的。它會就地執行回呼，所以每一筆回報都會在 `call_tool` 回傳之前送達。換成真正的傳輸方式，通知會和結果競速，一個慢的回呼在 `call_tool` 回傳之後可能還在執行。

### 試試看 {#try-it}

把 `client.py` 放在 `server.py` 旁邊，然後執行：

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

伺服器上的每一個 `await ctx.report_progress(...)` 都變成用戶端上對 `show` 的一次呼叫，依序發生，而且兩行都在 `call_tool` 回傳**之前**印出。進度不會打包進結果裡；它在工具還在執行時就持續串流過來。

!!! warning
    `progress_callback` 屬於那一次**呼叫**，不屬於 `Client`。沒有對應的建構子引數，因為不同的呼叫想要不同的回呼：這一次驅動下載進度條，下一次是一行記錄。

!!! check
    現在刪掉 `progress_callback=show`，再執行一次：

    ```text
    {'result': 'Imported 2 records.'}
    ```

    沒有錯誤、沒有警告，結果一樣。**呼叫端沒有要求進度時，`report_progress` 什麼都不做**，所以無條件回報就好，永遠不必去猜有沒有人在聽。

## 不知道總量的時候 {#when-you-dont-know-the-total}

`total` 是給知道分母時用的。常常並不知道：正在消化一個 feed、沿著游標往下走，或下載一個沒有長度標頭的東西。

那就省略它：

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

回呼會收到 `total=None`。用戶端還是可以顯示**有在動**（「3 imported so far...」），但沒辦法顯示百分比。不要為了讓進度條好看一點就捏造一個總量。

!!! tip
    `progress` 不一定要數某個特定的東西。位元組、資料列、頁數：挑使用者認得的單位，而且只承諾做得到的 `total`。

## 重點回顧 {#recap}

* 在任何接收 `Context` 的工具裡呼叫 `await ctx.report_progress(progress, total=None, message=None)`。
* 用戶端把 `progress_callback=` 傳給 `call_tool`：逐次呼叫，永遠不是設在 `Client` 上。
* 回呼的形式是 `async (progress, total, message) -> None`，在工具還在執行時就會觸發。
* 呼叫時沒有回呼，`report_progress` 就什麼都不做。無條件回報就好。
* 不知道 `total` 就省略；回呼會收到 `None`。

進度是執行中的工具給**使用者**看的。它為**你**（操作伺服器的人）記下的那些行，是另一條通道：**[記錄](logging.md)**。
