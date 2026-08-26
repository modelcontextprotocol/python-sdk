---
translation:
  sections: [0d6c05bcbf836bf3, 59a7b14eeefc68c1, 7114d8d6daba203f, e8bbb56a98ba7bc9, 5138010f6159901c, f78da7c7c363d4c6, 220a939cab348686]
  tool: 1
---
# 第一步 {#first-steps}

**[首页](../index.md)** 节奏很快：写一个服务器，运行它，调用一个工具。

这一页慢慢来：服务器能暴露的三样东西全都讲到，沿途遇到的每个概念也都给出名字。

## 宿主、客户端和服务器 {#host-client-and-server}

从这里开始，每一页都会见到这三个词：

* **宿主** 是 LLM 应用：Claude、IDE、智能体运行时。用户与之对话的就是它。
* **客户端** 位于宿主内部，讲 MCP。宿主每连接一个服务器，就运行一个客户端。
* **服务器** 是你用这个 SDK 构建的东西。它向客户端暴露内容，从不直接和模型对话。

你写的是服务器。宿主是别人的产品。SDK 还提供了一个 `Client`，你会用它来测试自己的服务器，本页后面就会用到。

## 三种原语 {#the-three-primitives}

服务器暴露的东西恰好有三种。区分它们的标准是 **谁来决定使用它们**：

| 原语       | 由谁控制 | 是什么                         | 示例                      |
|------------|----------|--------------------------------|---------------------------|
| **工具**   | 模型     | 模型为执行操作而调用的函数     | 一次 API 调用、一次数据库写入 |
| **资源**   | 应用     | 宿主加载进模型上下文的数据     | 文件内容、API 响应         |
| **提示词** | 用户     | 用户按名称调用的可复用消息模板 | 斜杠命令、菜单项           |

“由谁控制”正是这样划分的全部意义。工具会运行，是因为 **模型** 决定调用它。资源会被附加进来，是因为 **应用** 认为模型需要它。提示词会运行，是因为 **用户** 选了它。

!!! info
    如果你做过 Web API，大部分直觉其实已经有了：**资源** 相当于 `GET`（加载数据，什么都不改），**工具** 相当于 `POST`（干活，可能有副作用）。**提示词** 在 HTTP 里没有对应物，它更接近一个用户按名称运行的已保存查询。

## 一个服务器，三样俱全 {#one-server-all-three}

```python title="server.py" hl_lines="6 12 18"
--8<-- "docs_src/first_steps/tutorial001.py"
```

三个普通函数，三个装饰器。每个装饰器就是注册的全部：

* `@mcp.tool()` 把 `add` 变成 **工具**。
* `@mcp.resource("greeting://{name}")` 把 `greeting` 变成 **资源模板**：URI 里的 `{name}` 就是函数的参数。
* `@mcp.prompt()` 把 `summarize` 变成 **提示词**。它返回的字符串会成为一条用户消息。

其余的一切（名称、描述、参数模式），SDK 都从函数本身读取：函数名、文档字符串、类型注解。这些你都没有单独声明过。

!!! tip
    SDK 的两半各有一条导入路径：`from mcp import Client` 和 `from mcp.server import MCPServer`。不存在 `from mcp import MCPServer` 这种写法。

### 试一试 {#try-it}

用 MCP Inspector 运行它：

```console
uv run mcp dev server.py
```

打开它打印出来的 URL。Inspector 为每种原语各设一个标签页，按顺序逐个看一遍。

**工具。** 只有一项：`add`，描述是“Add two numbers.”。表单里有一个必填的整数字段 `a`，另一个是 `b`。填好后调用，结果是 `3`。这张表单是 Inspector 根据 `a: int, b: int` 生成的。其他所有客户端也都这样做。

**资源。** “Resources”列表是空的。`greeting` 在 **Resource Templates** 下面，因为 `greeting://{name}` 带有参数：在有人给出 `name` 之前，没有哪个具体的资源可以列出。填入 `World` 并读取：

```text
Hello, World!
```

**提示词。** 只有一项：`summarize`，带一个必填参数 `text`。传一段文本去获取它，会收到一条 `role: user` 的消息，内容就是你渲染出的字符串。提示词就是这么回事：一个构建消息的函数。

Inspector 是通过 **stdio** 运行你的服务器的，这是 MCP 服务器可用的传输方式之一。现在还不用选；**[运行服务器](../run/index.md)** 专门讲这个。

## 能力 {#capabilities}

你在 Inspector 里看到了三个标签页。它怎么知道有三个？

客户端连接时，服务器会声明自己的 **能力**：它会响应哪几类请求。客户端根据这份声明来决定该请求什么。这份声明你从没写过；是 `MCPServer` 替你声明的。

自己看一下。SDK 的 `Client` 可以直接接受服务器对象，并在 **内存中** 与之连接（没有子进程，没有端口）：

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

这个字典就是你的服务器所声明的 **能力**。每个连接上来的客户端最先得知的就是它：

| 能力        | 客户端现在可以调用                                          |
|-------------|------------------------------------------------------------|
| `tools`     | `tools/list`, `tools/call`                                  |
| `resources` | `resources/list`, `resources/templates/list`, `resources/read` |
| `prompts`   | `prompts/list`, `prompts/get`                               |

`MCPServer` 三种原语都提供，所以这三项始终都会声明。

注意这里缺了什么。`completions`（资源模板和提示词的参数自动补全）需要一个由你编写的处理函数，而这个服务器没有，所以这项能力不会出现，行为规范的客户端也就不会去问。所有可选项都遵循这条规则：注册了对应的东西，能力就出现；**[补全](../servers/completions.md)** 会证明这一点。

!!! info
    `Client(mcp)` 正是这些文档里每个示例测试时所用的那个内存客户端，你测试自己的服务器也会用它。它有整整一页：**[测试](testing.md)**。

## 你没有写的东西 {#what-you-did-not-write}

回头看看这一页。你写了三个小小的 Python 函数。你 **没有** 写：

* JSON Schema。`a: int, b: int` **就是** `add` 的模式。
* 请求处理函数。`tools/list`、`resources/read`、`prompts/get`：全都替你处理好了。
* 能力声明。`MCPServer` 替你生成了。
* 一行协议代码。版本协商、JSON-RPC 分帧、能力交换：全都发生在 `mcp dev` 和 `Client(mcp)` 内部，你一眼都没见到。

这个比例，正是这个 SDK 的意义所在。

## 回顾 {#recap}

* **宿主** 是 LLM 应用，**客户端** 是它讲 MCP 的那一半，**服务器** 是你构建的东西。
* 工具由 **模型** 控制，资源由 **应用** 控制，提示词由 **用户** 控制。
* 每种原语一个装饰器：`@mcp.tool()`、`@mcp.resource(uri)`、`@mcp.prompt()`。名称、描述和模式都来自函数本身。
* 带 `{param}` 的 URI 生成的是资源 **模板**，与具体资源分开列出。
* 服务器的 **能力** 会替你声明好，而客户端只会请求服务器声明过的内容。
* `Client(mcp)` 在内存中连接服务器对象：从第一天起，它就是你的测试工具。

接下来是 **[连接到真实宿主](real-host.md)**：把这个服务器真正放进 Claude Desktop 或 IDE 里。然后是 **[测试](testing.md)**：一页内容，一个内存客户端，从此不用再猜它到底能不能用。再之后，每种原语各有自己的一页，从模型驱动的那一种开始：**[工具](../servers/tools.md)**。
