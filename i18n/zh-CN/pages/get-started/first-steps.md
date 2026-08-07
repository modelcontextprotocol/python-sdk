# 第一步 {#first-steps}

**[首页](../index.md)** 节奏很快：写一个服务器、运行它、调用一个工具。

这一页走得慢一些，把服务器能暴露的三样东西都过一遍，并且沿途给每样东西一个名字。

## 宿主、客户端和服务器 {#host-client-and-server}

从这里开始，每一页都会出现的三个词：

* **宿主**是 LLM 应用：Claude、IDE、某个 agent 运行时。它就是用户在对话的那个东西。
* **客户端**住在宿主里面，负责讲 MCP。宿主每连接一个服务器，就运行一个客户端。
* **服务器**是你用这个 SDK 构建的东西。它向客户端暴露能力，从不直接和模型对话。

你写的是服务器。宿主是别人的产品。SDK 也给了你一个 `Client`，用它来测试你的服务器，本页后面就会出现。

## 三种原语 {#the-three-primitives}

一个服务器恰好暴露三类东西。区分它们的是**由谁决定使用它们**：

| 原语         | 由谁控制   | 它是什么                                | 示例                    |
|--------------|-----------|-----------------------------------------|-------------------------|
| **工具**     | 模型      | 模型调用来执行动作的函数                 | 一次 API 调用、一次数据库写入 |
| **资源**     | 应用      | 宿主加载进模型上下文的数据               | 文件内容、API 响应       |
| **提示词**   | 用户      | 用户按名称调用的可复用消息模板           | 一个斜杠命令、一个菜单项 |

“由谁控制”正是这种划分的全部要点。工具运行，是因为**模型**决定调用它。资源被附加进来，是因为**应用**判断模型需要它。提示词运行，是因为**用户**选了它。

!!! info
    如果你写过 Web API，大部分直觉你已经有了：**资源**相当于 `GET`
    （只加载数据，不改变任何东西），**工具**相当于 `POST`（它会做事，并且可能有
    副作用）。**提示词**没有对应的 HTTP 类比，它更接近用户按名称运行的一条保存好的查询。

## 一个服务器，三者齐全 {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

三个普通函数，三个装饰器。每个装饰器就是全部的注册工作：

* `@mcp.tool()` 让 `add` 成为一个**工具**。
* `@mcp.resource("greeting://{name}")` 让 `greeting` 成为一个**资源模板**：URI 里的 `{name}` 就是函数的参数。
* `@mcp.prompt()` 让 `summarize` 成为一个**提示词**。它返回的字符串会变成一条用户消息。

其余的一切（名称、描述、参数模式）SDK 都从函数本身读取：它的名字、它的文档字符串、它的类型标注。你从来不用单独声明这些。

!!! tip
    SDK 的两半有两条导入路径：`from mcp import Client` 和
    `from mcp.server import MCPServer`。不存在 `from mcp import MCPServer`。

### 试一试 {#try-it}

用 MCP Inspector 运行它：

```console
uv run mcp dev server.py
```

打开它打印出的 URL。Inspector 每种原语各有一个标签页，按顺序逐个看。

**工具。** 只有一项：`add`，描述是“Add two numbers.”。表单里有一个必填的整数字段 `a`，还有一个 `b`。填好、调用，结果是 `3`。这个表单是 Inspector 根据 `a: int, b: int` 生成的。其他客户端也一样。

**资源。** **Resources** 列表是空的。`greeting` 在 **Resource Templates** 下面，因为 `greeting://{name}` 带了参数：在有人提供 `name` 之前，没有一个具体的资源可以列出。给它 `World` 然后读取：

```text
Hello, World!
```

**提示词。** 只有一项：`summarize`，带一个必填参数 `text`。传入一些文本获取它，你会收到一条消息，`role: user`，内容是渲染后的字符串。提示词就是这么回事：一个构建消息的函数。

Inspector 通过 **stdio** 运行了你的服务器，这是 MCP 服务器可以讲的传输方式之一。现在还不用选，**[运行你的服务器](../run/index.md)** 那一页专门讲这个。

## 能力 {#capabilities}

你在 Inspector 里看到了三个标签页。它怎么知道有三个？

客户端连接上来时，服务器会声明它的**能力**：它会响应哪几类请求。客户端根据这份声明来决定该问什么。这段声明你从来没写过，`MCPServer` 替你声明了。

自己看看。SDK 的 `Client` 直接接受服务器对象，并**在内存中**连接它（没有子进程，也没有端口）：

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

那个字典就是你的服务器声明的**能力**。它是每个连上来的客户端最先了解到的东西：

| 能力         | 客户端现在可以调用                                           |
|-------------|------------------------------------------------------------|
| `tools`     | `tools/list`、`tools/call`                                  |
| `resources` | `resources/list`、`resources/templates/list`、`resources/read` |
| `prompts`   | `prompts/list`、`prompts/get`                               |

`MCPServer` 提供全部三种原语，所以三者总是都会被声明。

注意没出现的东西。`completions`（资源模板和提示词的参数自动补全）需要你自己写一个处理函数，这个服务器没有，所以这项能力不存在，行为良好的客户端也不会去问。所有可选项都是这个规则：注册了东西，能力就出现；**[补全](../servers/completions.md)** 会证明这一点。

!!! info
    `Client(mcp)` 就是这份文档中每个示例用来测试的那个内存内客户端，你也会用它来测试自己的
    服务器。它有专门的一页：**[测试](testing.md)**。

## 你没有写的东西 {#what-you-did-not-write}

回头看看这一页。你写了三个小小的 Python 函数。你**没有**写：

* JSON Schema。`a: int, b: int` **就是** `add` 的模式。
* 请求处理函数。`tools/list`、`resources/read`、`prompts/get`：全都替你处理好了。
* 能力声明。`MCPServer` 替你生成了。
* 一行协议代码。版本协商、JSON-RPC 帧封装、能力交换：全都发生在 `mcp dev` 和 `Client(mcp)` 内部，你从头到尾都没看见。

这个比例就是 SDK 的全部意义。

## 回顾 {#recap}

* **宿主**是 LLM 应用，**客户端**是它讲 MCP 的那一半，**服务器**是你构建的东西。
* 工具由**模型**控制，资源由**应用**控制，提示词由**用户**控制。
* 每种原语一个装饰器：`@mcp.tool()`、`@mcp.resource(uri)`、`@mcp.prompt()`。名称、描述和模式都来自函数本身。
* 带 `{param}` 的 URI 构成资源**模板**，它与具体资源分开列出。
* 服务器的**能力**是替你声明的，客户端只会去问服务器声明过的东西。
* `Client(mcp)` 在内存中连接服务器对象：从第一天起就是你的测试工具。

下一步是 **[连接到真实宿主](real-host.md)**：把这个服务器真正放进 Claude Desktop 或者 IDE 里。然后是 **[测试](testing.md)**：一页内容、一个内存内客户端，从此不用靠猜它能不能跑。再往后，每种原语各有一页，从模型驱动的那个开始：**[工具](../servers/tools.md)**。
