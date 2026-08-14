---
translation:
  sections: [6048b4f308edbb8c, 068bda0f21ee9c1b, c3e565b61acd75c5, c62422b159c6ed09, 47204fab253cc45c]
  tool: 1
---
# 中间件 {#middleware}

**中间件**（middleware）是一个异步函数，它包裹服务器收到的每一条消息。

把它写成 `async (ctx, call_next)`，再追加到 `server.middleware` 里。整个 API 就这些。

!!! warning
    中间件列表在源码中标记为**临时性**（provisional）：它的签名和语义可能在某个 2.x 次版本中改变。用它来**观察**（计时、记录日志、追踪）和**拒绝**消息；不要把它当作服务器赖以立足的根基。

`MCPServer` 在构造时接收这个列表（`MCPServer(name, middleware=[...])`），并以 `mcp.middleware` 暴露出来；低层 `Server` 把同一个列表暴露为 `server.middleware`。下面的示例用的是低层 `Server`；如果你还没见过 `Server(name, on_call_tool=...)`，先读 **[低层 Server](low-level-server.md)**。

## 一个计时中间件 {#a-timing-middleware}

一个服务器、一个工具、一个中间件，记录每条消息花了多长时间：

```python title="server.py" hl_lines="39-45 49"
--8<-- "docs_src/middleware/tutorial001.py"
```

* `ctx` 就是处理函数收到的那个 `ServerRequestContext`。`ctx.method` 是原始的方法字符串；`ctx.params` 是原始参数，**尚未**经过任何校验。
* `call_next(ctx)` 运行链条剩下的部分：校验、查找处理函数、你的处理函数。把它的返回值原样返回，响应就不会被改动。
* `try`/`finally` 是有意为之：抛出异常的处理函数照样会被计时，因为失败会以 `call_next` 抛出的异常的形式到达你的中间件。
* `server.middleware.append(...)` 完成注册。列表按从外到内的顺序执行，所以 `middleware[0]` 是离线路最近的那一个。

### 试一试 {#try-it}

连接一个客户端，列出工具，调用其中一个。日志里有**三**行：

```text
server/discover took 18.3 ms
tools/list took 0.1 ms
tools/call took 0.1 ms
```

你发了两次调用，却得到三行。第一行是 `server/discover`：客户端为建立连接而发送的请求，在你提出任何要求之前就发出了。

这正是关键所在。中间件包裹**每一条**入站消息：

* 连接建立：`server/discover`，或者旧版会话上的 `initialize` 和 `notifications/initialized`。
* 每一个请求和每一个通知。对于通知，`ctx.request_id is None`，`call_next(ctx)` 返回 `None`，而你返回的任何东西都会被丢弃。
* 甚至包括服务器没有处理函数的方法：`call_next` 会抛出 `MCPError(-32601, "Method not found")`，**穿过**你的中间件送往客户端。

## 在中间件里能做什么 {#what-you-can-do-inside-one}

按你应当犹豫的程度递增排列：

* **观察。**计时、计数、记录日志。就是上面的例子。
* **拒绝。**抛出一个 `MCPError` 来**代替**调用 `call_next(ctx)`，这一条消息就会以 JSON-RPC 错误作答。连接保持不断；下一条消息照常通过。服务器就是这样按调用方对 `subscriptions/listen` 设限的：订阅页面的 **[决定谁可以监听](../handlers/subscriptions.md#deciding-who-may-watch)** 一节有完整的讲解。
* **改写。**`ctx` 是一个 dataclass：`await call_next(dataclasses.replace(ctx, params=...))` 会把与客户端所发不同的参数交给链条剩下的部分。永远不要对 `initialize` 这样做：客户端拿到的结果是根据你改写后的参数构建的，但服务器提交连接状态时依据的是线路上的原始参数。两端可能在握手结束时对协商结果各执一词。
* **作答。**不调用 `call_next(ctx)` 而直接返回一个结果，它就会作为你的响应发给客户端。`call_next` 交给你的是最终的线路形式，而流水线从不修补你返回的内容，所以整个信封都由你负责：在 2026 年代的连接上，这包括 `serverInfo` 的 `_meta` 戳记——SDK 会给处理函数的结果加上它，但不会给你的结果加。

!!! check
    `initialize` 也是中间件包裹的对象之一，而且中间件是你能拿到的**唯一**钩子。试图用 `add_request_handler` 接管它，SDK 会拒绝：

    ```text
    ValueError: 'initialize' is handled by the server runner and cannot be overridden;
    use Server.middleware to observe or wrap initialization
    ```

!!! warning
    `initialize` 是内联处理的：在你的中间件链返回之前，服务器不会再读取任何入站消息。因此，在处理 `initialize` 期间等待一个服务器到客户端的请求（`ctx.session.send_request(...)`、一次征询（elicitation））会**让连接死锁**：你在等待的响应永远无法被读到。发后即忘的通知没有问题。

## 唯一一个默认启用的中间件 {#the-one-middleware-that-ships-on-by-default}

SDK 自带的中间件恰好只有一个，而且已经在你服务器的列表上了：为每条消息发出一个 OpenTelemetry span 的那个。你不用追加它，大多数时候也不用去想它。在你安装导出器之前它什么都不做，它有自己的页面：**[OpenTelemetry](../run/opentelemetry.md)**。

!!! info
    如果你写过 ASGI 中间件，这个形状你已经认识了。Starlette 的 `(scope, receive, send)` 变成了 `(ctx, call_next)`，而且它运行在传输**之后**，作用于解码后的消息而不是原始 HTTP 请求。两者可以组合：挂在 `streamable_http_app()` 上的 Starlette 中间件看到的是 HTTP；这里看到的是 MCP。

## 回顾 {#recap}

* 中间件是 `async (ctx, call_next) -> result`，以 `MCPServer(middleware=[...])` 传入（或追加到 `mcp.middleware`），在低层 `Server` 上则追加到 `server.middleware`。
* 它包裹**每一条**入站消息（`server/discover`、`initialize`、请求、通知、未知方法），按从外到内的顺序执行。
* 用 `ctx.request_id is None` 区分通知和请求。
* 抛出异常而不调用 `call_next` 即可拒绝一条消息；连接不受影响。
* SDK 自己的 OpenTelemetry 追踪也是一个中间件，已经在列表上了。见 **[OpenTelemetry](../run/opentelemetry.md)**。
* 整个接口都是临时性的。用它来观察；不要在它之上构建。

包裹请求的东西就这些了。**[授权](../run/authorization.md)** 决定的则是请求究竟能不能运行。
