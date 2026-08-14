---
translation:
  sections: ['4926721070127497', c52a1de2b6b32f40, 2e410b412c25f314, 627195f7159e24ef]
  tool: 1
---
# 测试 {#testing}

Python SDK 提供了一个带**内存传输**的 `Client` 类：把服务器对象传给它，它就会直接连接上去。

不用子进程，不占端口，根本不走任何传输。思路和 FastAPI 的 `TestClient` 一样。

## 基本用法 {#basic-usage}

假设有一个简单的服务器，只有一个工具：

```python title="server.py"
--8<-- "docs_src/testing/tutorial001.py"
```

要运行下面的测试，还需要两个额外的（开发）依赖项：

=== "uv"

    ```bash
    uv add --dev pytest inline-snapshot
    ```

=== "pip"

    ```bash
    pip install pytest inline-snapshot
    ```

!!! info
    本文档假设你已经熟悉 [`pytest`](https://docs.pytest.org/en/stable/)。

    下面的测试用 [`inline-snapshot`](https://15r10nk.github.io/inline-snapshot/latest/) 在一行里对整个结果对象做断言。它会把测试的输出记录成你看到的 `snapshot(...)` 字面量。如果不想用它，去掉这行 import，像其他任何测试一样对关心的字段做断言（`result.content[0].text == "3"`）即可。

下面是测试：

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

1. 如果用的是 `trio`，就改为返回 `"trio"`。详见 [anyio 文档](https://anyio.readthedocs.io/en/stable/testing.html#specifying-the-backends-to-run-on)。
2. 这个 fixture 产出一个已连接的客户端。每个接收 `client` 的测试，都会拿到一条连向同一服务器的全新内存连接。

这样就行了。接下来可以扩展测试，覆盖更多场景。

## 为什么用 `raise_exceptions=True`？ {#why-raise_exceptionstrue}

可能出错的情况有两种，而这个标志只管其中一种。

**你的工具**内部抛出的异常不算协议失败。它会变成一个带 `is_error=True` 的普通结果，模型会读到其中的消息。`raise_exceptions` 不会改变这一点：不管有没有它，`call_tool` 返回的都是同一个 `is_error=True` 结果。有一整页专门讲这个：**[处理错误](../servers/handling-errors.md)**。

工具函数体**之外**的失败则不同。在 `Client(mcp)` 提供的这条连接上，服务器会先把它脱敏成一条笼统的 `"Internal server error"`，客户端才会看到。意外崩溃的细节绝不应该泄露给远程调用方。但在测试里，这恰恰是你**不**想要的，也正是 `raise_exceptions=True` 所改变的：测试看到的是真实的消息，而不是脱敏后的那条。

测试里就让它开着。它在生产代码中没有意义。

## 默认在进程内 {#in-process-by-default}

!!! note
    `Client(mcp)` 在进程内连接，默认**不区分协议时代**：它会先探测服务器，再选择合适的协议路径。如果测试要验证旧版（legacy）特有的语义（采样（sampling）或征询（elicitation）的推送、`message_handler`），就固定使用 `mode="legacy"`，并在这种情况下去掉 `raise_exceptions=True`：旧版连接本来就不做脱敏，而这个标志会让失败在服务器任务内部重新抛出，而不是抛到你的测试里。

也正是因为这一行，本文档才敢保证其中的示例都能跑通：每个示例文件都会在 SDK 自己的测试套件里跑一遍，而且几乎全都正是通过这个客户端。你用的，就是 SDK 用来测试自己的同一个工具。

现在你有了一个可用且经过测试的服务器。要把它接入真实的应用（Claude Desktop、IDE），见 **[连接到真实宿主](real-host.md)**；以其他任何方式对外提供它，见 **[运行服务器](../run/index.md)**。
