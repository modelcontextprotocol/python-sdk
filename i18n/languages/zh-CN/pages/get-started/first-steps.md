# 第一步 {#first-steps}

**[首页](../index.md)** 的节奏很快：写一个服务器，运行它，调用一个工具。

这一页会慢一些，把服务器能暴露的三样东西都讲一遍，并为沿途的每样东西取个名字。

## 宿主、客户端和服务器 {#host-client-and-server}

从这里开始，每一页都会出现的三个词：

* **宿主**就是 LLM 应用：Claude、某个 IDE、某个 agent 运行时。它是用户正在对话的那一方。
* **客户端**住在宿主内部，负责讲 MCP。宿主每连接一个服务器，就运行一个客户端。
* **服务器**是你用这个 SDK 构建的东西。它向客户端暴露内容，从不直接和模型对话。

你写的是服务器。宿主是别人的产品。SDK 同时也提供了一个 `Client`，你会用它来测试自己的服务器，本页后面就会见到它。

## 三种原语 {#the-three-primitives}

服务器能暴露的东西恰好有三类。区分它们的是**由谁决定使用它们**：

| 原语       | 控制方     | 它是什么                                     | 示例                        |
|------------|------------|----------------------------------------------|-----------------------------|
| **工具**   | 模型       | 模型调用来执行动作的函数                     | 一次 API 调用、一次数据库写入 |
| **资源**   | 应用       | 宿主加载进模型上下文的数据                   | 某个文件的内容、某个 API 响应 |
| **提示词** | 用户       | 用户按名称调用的可复用消息模板               | 一个斜杠命令、一个菜单项     |

“控制方”正是这种划分的全部意义。工具之所以运行，是因为**模型**决定调用它。资源之所以被附加进来，是因为**应用**判断模型需要它。提示词之所以运行，是因为**用户**选中了它。

!!! info
    如果你写过 Web API，大部分直觉已经有了：**资源**相当于 `GET`
    （只加载数据，不改变任何东西），**工具**相当于 `POST`（它会做事，可能有
    副作用）。**提示词**没有对应的 HTTP 类比，它更接近用户按名称运行的一条
    保存好的查询。

## 一个服务器，三样齐全 {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

三个普通函数，三个装饰器。每个装饰器就是全部的注册工作：

* `@mcp.tool()` 让 `add` 成为一个**工具**。
* `@mcp.resource("greeting://{name}")` 让 `greeting` 成为一个**资源模板**：URI 里的 `{name}` 就是函数的参数。
* `@mcp.prompt()` 让 `summarize` 成为一个**提示词**。它返回的字符串会变成一条用户消息。

其余的一切（名称、描述、参数模式）SDK 都从函数本身读取：函数名、文档字符串、类型注解。你从没单独声明过任何一项。

!!! tip
    SDK 的两半有两条导入路径：`from mcp import Client` 和
    `from mcp.server import MCPServer`。没有 `from mcp import MCPServer` 这种写法。

### 试一试 {#try-it}

用 MCP Inspector 运行它：

```console
uv run mcp dev server.py
```

打开它打印出的 URL。Inspector 为每种原语提供一个标签页，按顺序走一遍。

**工具。** 只有一条：`add`，描述是“Add two numbers.”。表单里有一个必填的整数字段 `a`，还有一个 `b`。填好并调用，结果是 `3`。这个表单是 Inspector 根据 `a: int, b: int` 生成的。其他所有客户端也一样。

**资源。** “Resources”列表是空的。`greeting` 在 **Resource Templates** 下面，因为 `greeting://{name}` 带了一个参数：在有人提供 `name` 之前，没有哪个具体资源可以列出来。给它填上 `World` 并读取：

```text
Hello, World!
```

**提示词。** 只有一条：`summarize`，带一个必填的 `text` 参数。传入一些文本获取它，你会收到一条消息，`role: user`，内容就是渲染后的字符串。提示词就是这么回事：一个构建消息的函数。

Inspector 通过 **stdio** 运行了你的服务器，这是 MCP 服务器可以使用的传输方式之一。现在还不用选，**[运行你的服务器](../run/index.md)** 才是讲这个的页面。

## 能力 {#capabilities}

你在 Inspector 里看到了三个标签页。它是怎么知道有三个的？

客户端连接时，服务器会声明自己的**能力**：它愿意响应哪些族的请求。客户端据此决定该不该发出某个请求。这份声明你从没写过，`MCPServer` 替你声明了。

自己看一眼。SDK 的 `Client` 可以直接接收服务器对象，并**在内存中**连接它（没有子进程，也没有端口）：

```python
import asyncio

from mcp import Client

from server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        print(client.server_capabilities.model_dump(exclude_none=True))


asyncio.run(main())
```

```text
{'prompts': {'list_changed': True}, 'resources': {'subscribe': True, 'list_changed': True}, 'tools': {'list_changed': True}}
```

这个字典就是你的服务器声明的**能力**。它是每个接入的客户端最先了解到的东西：

| 能力        | 客户端现在可以调用                                             |
|-------------|----------------------------------------------------------------|
| `tools`     | `tools/list`、`tools/call`                                     |
| `resources` | `resources/list`、`resources/templates/list`、`resources/read` |
| `prompts`   | `prompts/list`、`prompts/get`                                  |

`MCPServer` 服务全部三种原语，所以这三项总是会被声明。

注意看缺了什么。`completions`（为资源模板和提示词提供参数自动补全）需要一个由你编写的处理函数，这个服务器没有，所以这项能力不存在，行为良好的客户端也就不会去请求它。所有可选项都遵循这条规则：注册了对应的东西，能力就出现了；**[补全](../servers/completions.md)** 会证明这一点。

!!! info
    `Client(mcp)` 就是这份文档里每个示例用来测试的那个内存客户端，你也会用它来测试自己的代码。
    它有专门的一页：**[测试](testing.md)**。

## 你没有写的东西 {#what-you-did-not-write}

回头看看这一页。你写了三个小小的 Python 函数。你**没有**写：

* 一份 JSON Schema。`a: int, b: int` **就是** `add` 的模式。
* 一个请求处理函数。`tools/list`、`resources/read`、`prompts/get`：全都替你处理好了。
* 一份能力声明。`MCPServer` 替你生成了。
* 一行协议代码。版本协商、JSON-RPC 分帧、能力交换：这一切都发生在 `mcp dev` 和 `Client(mcp)` 内部，你从没见过它们。

这个比例正是这个 SDK 的全部意义。

## 小结 {#recap}

* **宿主**是 LLM 应用，**客户端**是它讲 MCP 的那一半，**服务器**是你构建的东西。
* 工具由**模型**控制，资源由**应用**控制，提示词由**用户**控制。
* 每种原语一个装饰器：`@mcp.tool()`、`@mcp.resource(uri)`、`@mcp.prompt()`。名称、描述和模式都来自函数本身。
* 带 `{param}` 的 URI 构成一个资源**模板**，与具体资源分开列出。
* 服务器的**能力**是替你声明的，而客户端只会请求服务器声明过的东西。
* `Client(mcp)` 在内存中连接服务器对象：从第一天起就是你的测试工具。

接下来是 **[连接到真实宿主](real-host.md)**：把这个服务器真正放进 Claude Desktop 或某个 IDE 里。然后是 **[测试](testing.md)**：一页内容，一个内存客户端，你再也不用猜它能不能用。之后每种原语都有自己的一页，从模型驱动的那个开始：**[工具](../servers/tools.md)**。
