---
translation:
  sections: [ed4a756b4c53c585, 97e2fb315b7fe398, 4d04f1c6f4bf6c1d, 577d73078fc62baf]
  tool: 1
---
# 快速开始 {#get-started}

刚接触 MCP，或者刚接触这个 SDK？从这里开始。这几页会带你从零开始，做出一个能用、经过测试的服务器：[安装 SDK](installation.md)、构建[第一个服务器](first-steps.md)、[把它接入真实的宿主](real-host.md)，然后用内存客户端[测试它](testing.md)。

## 运行代码 {#run-the-code}

所有代码块都可以直接复制使用：它们都是完整、可运行的文件。

想跟着做，就把某个代码块粘贴到 `server.py` 里，再用 MCP Inspector 打开：

```console
uv run mcp dev server.py
```

**强烈建议**亲手写（或者复制）这些代码，改一改，然后在本地运行。只有在自己的编辑器里真正用上，才能体会到关键所在：要写的代码非常少，有自动补全，还没运行，类型检查就已经把错误找出来了。

## 不用靠猜 {#you-will-not-be-guessing}

这些文档中的每个示例，都是 SDK 自身仓库 [`docs_src/`](https://github.com/modelcontextprotocol/python-sdk/tree/main/docs_src) 目录下的完整文件；SDK 的测试套件会通过**内存客户端**把它们逐一运行一遍：

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

没有子进程，不占端口，也不经过任何传输。`Client(mcp)` 直接连到服务器对象上。

如果对 SDK 的某次改动弄坏了这些页面上的某个示例，CI 会在页面出问题之前先变红。这里读到的代码，就是实际运行的代码。

在[测试](testing.md)中你会亲手用到它；测试自己的服务器，用的也是这个方法。

## 接下来去哪里 {#where-to-go-next}

服务器跑起来之后，其余文档就是参考手册，而不是课程。每一页都自成一体，需要什么就直接跳过去看：

* 服务器对外暴露什么（工具、资源、提示词），见 **[服务器](../servers/index.md)**。
* 注册的函数内部有什么可用，见 **[在处理函数内部](../handlers/index.md)**。
* 怎样把它送到客户端面前（stdio、HTTP、现有的 FastAPI 应用），见 **[运行服务器](../run/index.md)**。
* 构建另一端，也就是**使用** MCP 服务器的应用，见 **[客户端](../client/index.md)**。
