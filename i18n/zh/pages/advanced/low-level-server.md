---
translation:
  sections: [2c79b6338e09b7ac, 7edc43b3fae11314, 1086e77ce561cd7f, a3f71823df5efc31, 9fc7109f72201cae, 7bf25983df655b66, 6330e1f4c6029683, 2f1749c8c133fa1c, b3530fcf4d11fd56, ebc33704fbd74262, cd0e9c933350390e]
  tool: 1
---
# 底层 Server {#the-low-level-server}

`@mcp.tool()` 是一层封装。它下面还有第二个服务器类 `Server`，说的是原始的 MCP：你把协议对象交给它，它原封不动地放到线路上。

`MCPServer` 就构建在它之上。当便利层碍事时，才需要下沉到这一层：

* 需要发出一个**精确**的模式（从文件加载、从数据库生成），而不是从 Python 签名推导出来的模式。
* 需要完全掌控结果：`_meta`、`is_error`、`structured_content` 的每一个键。
* 需要处理一个 MCP 没有定义的方法。

其他情况，留在 `MCPServer` 上。

## 同一个工具，手写版 {#the-same-tool-by-hand}

这是 **[工具](../servers/tools.md)** 用九行 `@mcp.tool()` 写出的 `search_books` 工具，去掉语法糖之后的样子：

```python title="server.py" hl_lines="22 26 32"
--8<-- "docs_src/lowlevel/tutorial001.py"
```

变了三件事，而它们就是整个底层 API：

* **处理函数是构造函数参数。** `on_list_tools=` 和 `on_call_tool=` 传进 `Server(...)`。这一层没有装饰器，每个处理函数的形状都一样：`async (ctx, params) -> result`。
* **输入模式自己写。** `Tool.input_schema` 是一个普通的 JSON Schema `dict`。没人从类型注解推导它，因为根本没有类型注解可供推导。
* **结果自己构建。** `CallToolResult(content=[TextContent(...)])`，手写。没有包装、没有转换，也不会从返回值注解推断任何东西。

`params` 是解析后的请求：`CallToolRequestParams` 提供 `.name` 和 `.arguments`。`ctx` 是一个 `ServerRequestContext`：`ctx.session` 用来回头和客户端通信，还有 `ctx.lifespan_context`、`ctx.request_id`，以及 `ctx.meta`——请求传入的 `_meta`。

!!! info
    如果用过 FastAPI，这层关系你已经熟悉了。`MCPServer` 是装饰器加类型注解的那一层；`Server` 是底下的 Starlette。它们不是竞争关系：`MCPServer` 会构造一个 `Server`，并在上面注册和这里一模一样的处理函数。

### 试一试 {#try-it}

这个没有 Inspector 可用：`mcp dev` 和 `mcp run` 只接受 `MCPServer`。内存中的 `Client` 不在乎；它接收底层 `Server` 的方式和接收 `MCPServer` 完全一样：

```python title="main.py"
import asyncio

from mcp import Client

from server import server


async def main() -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_books", {"query": "dune", "limit": 5})
        print(result.content)


asyncio.run(main())
```

```text
[TextContent(type='text', text="Found 3 books matching 'dune' (showing up to 5).", annotations=None, meta=None)]
```

和 `@mcp.tool()` 版本产生的文本一样。两处实实在在的差别：

* `result.structured_content` 是 `None`。高层服务器会替你把 `-> str` 包装成 `{"result": ...}`；在这里，你没构建的东西没人替你构建。
* `list_tools` 返回的是**你**敲进去的模式，一字不差。高层版本在每个属性上都有 `"title": "Query"`，根上还有一个 `"title": "search_booksArguments"`：Pydantic 的产物。在这一层，线路上有什么，都是你放上去的。

## 没有替你做任何检查 {#nothing-is-checked-for-you}

`MCPServer` 会在你的函数运行之前拒绝错误的参数，按它生成的模式校验调用（**[工具](../servers/tools.md)**）。

`Server` 不做这件事。你的 `input_schema` 只是向客户端**公布**；它从不会被**应用**到 `params.arguments` 上。

!!! check
    调用 `search_books` 时不传 `limit`，你的 `args["limit"]` 就会抛出 `KeyError`。客户端看到的是：

    ```text
    MCPError: Internal server error
    ```

    一个 JSON-RPC 错误，代码 `-32603`，消息故意写得很笼统：SDK 不会把你的 traceback 泄露给远程调用方。模型永远不知道自己哪里做错了，所以也没法重试。（在测试里，`raise_exceptions=True` 会把真实的异常暴露出来；见 **[测试](../get-started/testing.md)**。）

这一点可以推广。从底层处理函数抛出的异常**永远**是协议错误，绝不会是 `is_error=True` 的工具结果。如果想让模型读到失败信息并恢复，就自己校验 `params.arguments`，然后返回 `CallToolResult(content=[TextContent(...)], is_error=True)`。这两种失败是 **[处理错误](../servers/handling-errors.md)** 的主题。

## 两个工具，一个处理函数 {#two-tools-one-handler}

`on_call_tool` 是服务器上所有工具的唯一入口。按 `params.name` 路由：

```python title="server.py" hl_lines="38-43"
--8<-- "docs_src/lowlevel/tutorial002.py"
```

* `list_tools` 公布两个工具。`call_tool` 按名字分发。
* `else` 分支很重要：对于一个你从未列出的名字，`Server` 照样会把 `tools/call` 直接转发进你的处理函数。在那里抛异常，调用就会变成和上面一样的 `-32603`。

## 结构化输出，手写版 {#structured-output-by-hand}

在 `Tool` 上声明 `output_schema`，在结果上放 `structured_content`。两者都归你管：

```python title="server.py" hl_lines="19-23 36"
--8<-- "docs_src/lowlevel/tutorial003.py"
```

调用它，结果同时携带两种表示：

```json
{
  "content": [{"type": "text", "text": "Found 3 books matching 'dune'."}],
  "structuredContent": {"matches": 3, "query": "dune"},
  "isError": false,
  "resultType": "complete",
  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "Bookshop", "version": "2.0.0"}}
}
```

`_meta` 块是服务器的身份标记：SDK 会把它加到每个 2026 版的结果上，`version` 取自构造函数（没设置的服务器会报告空字符串）。不能暴露身份的服务器可以用中间件把这个键去掉，中间件拥有它返回的结果。

服务器从不比较这两个字段。本 SDK 的 `Client` 会：返回的 `structured_content` 不满足你声明的 `output_schema` 时，`call_tool` 会抛出一个 `RuntimeError`，开头是 `Invalid structured content returned by tool search_books`，后面引用 `jsonschema` 的失败信息。承诺一个模式很便宜；信守它是你的事。返回类型和模式的完整阶梯详见 **[结构化输出](../servers/structured-output.md)**。

## `_meta`：给应用程序，不是给模型 {#\_meta-for-the-application-not-the-model}

`content` 是答案里模型读取的部分。`structured_content` 是同一个答案的类型化数据形式。`_meta` 是第三条通道：随结果一起传递、面向**客户端应用程序**的数据，根本不属于答案的一部分。

用它放记录 ID、追踪 ID，以及任何 UI 需要而提示词不需要的东西：

```python title="server.py" hl_lines="37"
--8<-- "docs_src/lowlevel/tutorial004.py"
```

* 构造时写作 `_meta=`，也就是线路上的名字。客户端读回来是 `result.meta`。
* 给键加命名空间（`bookshop/record_ids`）。`io.modelcontextprotocol/*` 键由协议保留。

!!! warning
    `_meta` 是你和客户端应用程序之间的约定，不是对哪些内容会到达模型的保证。宿主决定渲染什么。永远不要把秘密放进工具结果的任何部分。

## 能力跟着处理函数走 {#capabilities-follow-your-handlers}

`Server` 公布的恰好是你给了处理函数的那些方法族。上面的 `Bookshop` 只传了 `on_list_tools` 和 `on_call_tool`，别的都没有，所以连接它的客户端看到的是：

```json
{"tools": {"listChanged": false}}
```

没有 `resources`，没有 `prompts`：没有东西支撑它们。传入 `on_list_prompts`，`prompts` 就出现；传入 `on_completion`，`completions` 就出现。

`MCPServer` 总是公布工具、资源和提示词，不管你有没有注册，因为它的管理器总是存在。在这一层，声明**就是**那次构造函数调用。

## 生命周期泛型 {#the-lifespan-generic}

`Server` 在生命周期产出的类型上是泛型的。注解一次，这个对象在出现的每个地方都有类型：

```python title="server.py" hl_lines="24-26 44-45 50"
--8<-- "docs_src/lowlevel/tutorial005.py"
```

* 生命周期是一个 `Callable[[Server[Catalog]], AbstractAsyncContextManager[Catalog]]`；在 `async` 生成器上加 `@asynccontextmanager` 正好得到它。
* 它 `yield` 的东西成为 `ctx.lifespan_context`，又因为处理函数注解为 `ServerRequestContext[Catalog]`，`.search(...)` 能自动补全并通过类型检查。
* 服务器启动时进入一次，停止时退出一次。启动、清理，以及 `MCPServer` 对同一思路的实现，详见 **[生命周期](../handlers/lifespan.md)**。

没有 `lifespan=` 时，`ctx.lifespan_context` 是一个空 `dict`。

## 自己的方法 {#a-method-of-your-own}

构造函数覆盖 MCP 定义的方法。`add_request_handler` 覆盖其余所有：

```python title="server.py" hl_lines="35-36 39-40 43-44 48"
--8<-- "docs_src/lowlevel/tutorial006.py"
```

* 第一个参数是方法字符串。通知有一个对应的 `add_notification_handler`。
* `params_type` 是传入的 `params` 在处理函数运行**之前**校验所依据的模型，所以自定义方法**确实**得到了工具没有的校验。继承 `RequestParams`，这样 `_meta` 字段的解析方式和其他方法一样。
* 处理函数返回 `BaseModel`、`dict` 或 `None`。SDK 把它序列化进 JSON-RPC 结果。

一个实实在在的提醒：高层 `Client` 只为 MCP 定义的方法提供了动词，所以没有 `client.reindex()`。厂商方法是给已经知道它存在的对端用的：你同时发布的客户端，或者你自己说 JSON-RPC 的另一个服务。

有一个方法你不能占用：

```text
ValueError: 'initialize' is handled by the server runner and cannot be overridden;
use Server.middleware to observe or wrap initialization
```

握手归运行器所有。`server/discover`、`ping` 以及其他所有内置方法都可以替换。

!!! tip
    那条错误里提到的 `Server.middleware` 会包裹**每一条**入站消息，包括 `initialize`。如果想要的是观察或改写流量，而不是响应一个新方法，从 **[中间件](middleware.md)** 开始。

## 其他处理函数 {#the-other-handlers}

下面每一项都是一个你现在已经有词汇去理解的概念；每一项都有自己的页面。

* `on_call_tool`、`on_get_prompt` 和 `on_read_resource` 可以返回 `InputRequiredResult` 而不是正常结果，来暂停调用并向客户端索要输入；见 **[多轮往返（multi-round-trip）请求](../handlers/multi-round-trip.md)**。符合这一层的风格，没有任何东西替你装好：`MCPServer` 默认会密封 `requestState`，而在这里，你设置的 `request_state` 按原样穿过线路，直到你用 `server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[...]), default_audience=server.name))` 主动启用：一行代码（两个名字都从 `mcp.server.request_state` 导入），得到和 `MCPServer` 完全相同的密封与验证（**[保护 `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**）。
* `on_list_resources`、`on_read_resource`、`on_list_prompts`、`on_get_prompt`、`on_completion` 是针对其他原语的同样 `(ctx, params) -> result` 形状。
* `on_subscriptions_listen` 提供 2026-07-28 的 `subscriptions/listen` 流。传入一个构建在 `SubscriptionBus` 之上的 `ListenHandler`，并从其他处理函数向总线发布事件；完整的组合方式见 **[订阅](../handlers/subscriptions.md)**。
* `server.streamable_http_app()` 返回的 Starlette 应用和 `MCPServer` 的一样；按 **[运行你的服务器](../run/index.md)** 部署任何其他 ASGI 应用的方式部署它。这一层没有 `server.run(transport=...)`：`server.run(read_stream, write_stream, server.create_initialization_options())` 在一对流上驱动一个连接，整件事就是这一行。

## 回顾 {#recap}

* 底层 `Server` 以 `on_*` **构造函数参数**接收处理函数；每个处理函数都是 `async (ctx, params) -> result`。
* `input_schema` 字典自己写，`CallToolResult` 自己构建。没有任何东西替你推导、包装或校验。
* 处理函数里的异常是 `-32603` 协议错误。模型能读到的工具错误是**你**返回的 `is_error=True` 的 `CallToolResult`。
* 结果上的 `_meta` 面向客户端应用程序，不是模型。
* `Server[T]` 在生命周期产出的东西上是泛型的；`ctx.lifespan_context` 是有类型的 `T`。
* `add_request_handler(method, params_type, handler)` 提供任意方法。`initialize` 是保留的。
* `Server` 公布的能力由你注册了哪些处理函数推导而来。

`Client(server)` 对两种服务器一视同仁，因为它们**就是**同一个协议，这正是关键所在。再往下一层根本不是一个类：它是 **[中间件](middleware.md)**。
