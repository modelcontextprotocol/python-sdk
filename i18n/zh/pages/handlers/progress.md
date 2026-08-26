---
translation:
  sections: [5315262fe26b33e1, 9d8e98840f1b78f0, 0284b215e85366c4, 8534d8dbb4053a70, 2966fac6fe697007]
  tool: 1
---
# 进度 {#progress}

一个要跑三十秒的工具，如果这三十秒里一声不吭，看起来就像坏了。

**进度通知**解决的就是这个问题。工具报告自己做到哪了；客户端决定拿它画什么：进度条、旋转指示器，还是一行日志。

## 从工具里报告 {#report-it-from-the-tool}

接收一个 **`Context`** 参数，然后调用 `report_progress`：

```python title="server.py" hl_lines="8 11"
--8<-- "docs_src/progress/tutorial001.py"
```

三个参数，含义由你决定：

* `progress`：做到哪了。规范要求它每次报告都**递增**；不要重复同一个值，也不要倒退。
* `total`：总共有多少，如果你知道的话。可选。
* `message`：描述**这一步**的一行人类可读文字。可选。

`ctx` 是因为类型注解被注入的，模型永远看不到它：`import_catalog` 的输入模式只有一个属性 `urls`。**[Context](context.md)** 页面专门讲这个对象；进度只是它提供的功能之一。

## 从客户端监听 {#listen-for-it-from-the-client}

客户端**按调用**选择接收，方法是给 `call_tool` 传 `progress_callback=`：

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

回调是一个 `async` 函数，接收的正是服务器报告的内容：`progress`、`total`、`message`。

!!! info
    `Client(mcp)` 直接在内存中连接到服务器对象，和 **[测试](../get-started/testing.md)** 页面所用的是同一个客户端。无论 `Client` 用哪种传输方式，`progress_callback` 都是同一个参数；接下来看到的**时序**则是内存连接特有的。它以内联方式运行你的回调，所以每条报告都在 `call_tool` 返回之前送达。换成真实的传输方式，通知会和结果竞速，`call_tool` 已经返回之后，一个慢的回调可能还在运行。

### 试一试 {#try-it}

把 `client.py` 放在 `server.py` 旁边，然后运行：

```console
python client.py
```

```text
Imported https://example.com/a.json (1/2)
Imported https://example.com/b.json (2/2)
{'result': 'Imported 2 records.'}
```

服务器上的每一次 `await ctx.report_progress(...)` 都变成了客户端上对 `show` 的一次调用，顺序不变，而且两行都在 `call_tool` 返回**之前**打印了出来。进度不会打包进结果里；它在工具还在干活的时候就流式送出。

!!! warning
    `progress_callback` 属于**调用**，而不是 `Client`。没有对应的构造函数参数，因为不同的调用想要不同的回调：这一次驱动下载进度条，下一次是一行日志。

!!! check
    现在删掉 `progress_callback=show`，再运行一次：

    ```text
    {'result': 'Imported 2 records.'}
    ```

    没有错误，没有警告，结果相同。`report_progress` **在调用方没有请求进度时是空操作**，所以可以无条件地报告，永远不用操心有没有人在听。

## 不知道总量时 {#when-you-dont-know-the-total}

`total` 用在知道分母的时候。很多时候并不知道：你在消费一个 feed、遍历一个游标、下载一个没有长度头的东西。

那就省略它：

```python title="server.py" hl_lines="20"
--8<-- "docs_src/progress/tutorial002.py"
```

回调收到的是 `total=None`。客户端仍然可以显示**有动静**（“目前已导入 3 条……”），但显示不了百分比。不要为了进度条好看而编造一个总量。

!!! tip
    `progress` 不一定非得数某样特定的东西。字节、行、页：选用户认得出的单位，并且只承诺你能兑现的 `total`。

## 回顾 {#recap}

* 在任何接收 `Context` 的工具里调用 `await ctx.report_progress(progress, total=None, message=None)`。
* 客户端给 `call_tool` 传 `progress_callback=`：按调用传，永远不在 `Client` 上设。
* 回调的形式是 `async (progress, total, message) -> None`，在工具还在运行时就会触发。
* 调用上没有回调，`report_progress` 就什么都不做。无条件地报告即可。
* 不知道 `total` 就省略；回调拿到的是 `None`。

进度是运行中的工具展示给**用户**看的。它为**你**——运维这台服务器的人——记录的那些日志行走的是另一条通道：**[日志](logging.md)**。
