---
translation:
  sections: [f3ca8ac5f90f2dfa, 85a1ef3588ba0736, 563346d4d5804933, 9e3528340d0bab53]
  tool: 1
---
# 生命周期 {#lifespan}

大多数真实的服务器在整个运行期间都会持有某样东西：数据库连接池、HTTP 客户端、加载好的模型。

你不想每次调用都重新构建它，又希望能干净地关闭它。这就是**生命周期（lifespan）**的用途。

## 带类型的生命周期 {#a-typed-lifespan}

生命周期是一个 `@asynccontextmanager`，它接收服务器并 `yield` **一个对象**。无论 yield 出什么，只要服务器在运行，每个处理函数都能用到它。

```python title="server.py" hl_lines="25-31 34 38 40"
--8<-- "docs_src/lifespan/tutorial001.py"
```

从下往上读：

* `app_lifespan` 在 `yield` **之前**连接 `Database`，并在**之后**的 `finally` 里断开连接。这就是启动和关闭。
* 它 yield 一个 `AppContext`，一个普通的 dataclass，装着你准备好的东西。今天是一个字段，明天可能是十个。
* `MCPServer("Bookshop", lifespan=app_lifespan)` 就是全部的接线。
* 在工具内部，yield 出的对象是 `ctx.request_context.lifespan_context`。

生命周期只运行**一次**。服务器启动时（第一个请求之前）进入，服务器停止时退出。其间的每个请求共享同一个 `AppContext`。

!!! info
    如果你写过 FastAPI 的 `lifespan`，这些你已经会了。同样的装饰器，同样的 `yield`，同样的 `finally`。

### 模型看到什么 {#what-the-model-sees}

没有新东西。`ctx` 是一个 **Context** 参数，所以 SDK 会注入它，它永远不会进入输入模式：

```json
{
  "type": "object",
  "properties": {
    "genre": {"title": "Genre", "type": "string"}
  },
  "required": ["genre"],
  "title": "count_booksArguments"
}
```

`genre` 是模型唯一能传入的参数。生命周期是服务器自己的事。

`@mcp.resource()` 和 `@mcp.prompt()` 函数也可以接收 `ctx` 参数，只是要写成裸的 `Context`，原因下一节会讲到。`ctx` 携带的所有内容详见 **[Context](context.md)**。

### 它确实带类型 {#it-really-is-typed}

再看一眼那个注解：`ctx: Context[AppContext]`。

正是这一个类型参数，让 `ctx.request_context.lifespan_context` 在类型检查器眼里**就是**一个 `AppContext`。`.db` 能自动补全；`.dbb` 在你运行服务器之前就会报错。

如果改写成裸的 `Context`，`lifespan_context` 的类型就是 `dict[str, Any]`：类型检查器无从知道你的生命周期 yield 了什么。运行时对象还在，只是失去了类型上的帮助。

!!! warning
    `Context[AppContext]` 是**仅限工具**的写法。把它放在 `@mcp.resource()` 或 `@mcp.prompt()` 函数上，对该处理函数的每次调用都会失败。客户端会收到一个错误，服务器日志会说明原因：

    ```text
    Context is not available outside of a request
    ```

    在资源和提示词里，写裸的 `ctx: Context`。生命周期 yield 出的对象在运行时仍然是 `ctx.request_context.lifespan_context`；你放弃的是类型参数，不是对象。

!!! tip
    生命周期总是存在。如果你不传，SDK 的默认实现会 yield 一个空 `dict`，所以 `ctx.request_context.lifespan_context` 是 `{}`，绝不会是 `None`。也正是因为这个默认值，裸的 `Context` 才把它的类型定为 `dict[str, Any]`。

## 亲眼看它发生 {#watch-it-happen}

“启动在第一个请求之前运行”这种话，不该只凭信任接受。

把服务器精简到只剩生命周期：给 `Database` 加一个 `connected` 标志，在 `connect()` 和 `disconnect()` 里翻转它，再加一个报告它的工具。

```python title="server.py" hl_lines="11 14 17 25 44"
--8<-- "docs_src/lifespan/tutorial002.py"
```

`database` 放在模块级别只有一个原因：这样就能从服务器**外部**观察它。

!!! check
    三个时刻，三个值：

    * 服务器启动前，`database.connected` 是 `False`。导入模块什么也没连接。
    * 运行期间，调用 `database_status`，结果是 `"connected"`。
    * 停止服务器，`finally` 块运行：`database.connected` 又变回 `False`。

    工作恰好发生在你放的位置：围绕 `yield`，不在导入时，也不是每个请求一次。

## 回顾 {#recap}

* `lifespan=` 接收一个 `@asynccontextmanager`，它接收服务器并 `yield` 一个对象。
* `yield` 之前的代码是启动。之后的 `finally` 是关闭。
* 它只运行一次，围绕服务器的整个生命，而不是每个请求一次。
* 无论 `yield` 出什么，它在每个工具、资源和提示词里都是 `ctx.request_context.lifespan_context`。
* `ctx: Context[AppContext]` 让这种访问在工具里完全带类型。资源和提示词用裸的 `Context`。
* 不传 `lifespan=` 意味着一个空 `dict`，绝不会是 `None`。

在调用中途停下来，向用户询问只有他们知道的事情的处理函数，详见 **[征询（elicitation）](elicitation.md)**。
