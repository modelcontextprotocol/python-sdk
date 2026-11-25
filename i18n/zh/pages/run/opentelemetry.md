---
translation:
  sections: [bc0227014724fa49, 15738c2f7fd67d86, a2c17bbe3f707e2f, d0d853376f162c06, b6368643fcc1c8d8, 902e33e17564a607]
  tool: 1
---
# OpenTelemetry {#opentelemetry}

你的服务器已经自带追踪，什么都不用加。

你创建的每个服务器都会为它处理的每条消息发出一个 [OpenTelemetry](https://opentelemetry.io/) span。这不是你写的，也不需要你导入。调用 `MCPServer(...)` 的那一刻，它就在了。

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

这就是一个完整的、带追踪的服务器。调用 `search_books`，就会为它创建一个 span。低层的 `Server` 也一样：追踪在两者上都有。

## 你能得到什么 {#what-you-get}

每条入站消息都会变成一个 `SERVER` span，名字由方法及其目标组成。所以针对 `search_books` 的 `tools/call` 对应的 span 是 `tools/call search_books`，而单独的 `tools/list` 就是 `tools/list`。

每个 span 带有几个属性：

* `mcp.method.name` 和 `mcp.protocol.version`，每个 span 上都有。
* `jsonrpc.request.id`，请求上才有（通知没有）。
* 处理函数抛出异常会把 span 状态设为 error。`is_error=True` 的工具结果也一样。

由于追踪工具调用是非常常见的需求，`tools/call` span 遵循 OpenTelemetry 的 [GenAI 语义约定](https://opentelemetry.io/docs/specs/semconv/gen-ai/)：

* `gen_ai.operation.name`，设为 `"execute_tool"`。
* `gen_ai.tool.name`，设为被调用的工具。

`prompts/get` span 同理带有 `gen_ai.prompt.name`。list 类方法不带 `gen_ai.*` 键，因为没有东西可命名。

!!! tip
    正是这些 GenAI 属性，让追踪 UI 能像对待其他任何 agent 一样对你的工具调用分组。这种分组是白送的，不需要额外代码。

## 想用之前零成本 {#it-costs-nothing-until-you-want-it}

这一点让“默认开启”成为一个让人放心的默认值。

SDK 只依赖 `opentelemetry-api`，也就是 OpenTelemetry 轻量的那一半。没有安装 SDK 和 exporter 时，创建 span 是空操作。所以你的服务器此刻发出的 span 几乎没有任何开销，也没有人在收集它们。

等到哪天想**看到**它们，就装上另一半，并把它指向某个地方：

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

按 OpenTelemetry 的常规方式配置一个 exporter，SDK 一直在默默创建的每个 span 就都亮起来了。服务器代码不用改，一行都不用。

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) 就是这样一个后端，而且它替你把配置做了：`pip install logfire`、`logfire.configure()`，你的 MCP span 就会出现在实时视图里。它构建在 OpenTelemetry 之上，所以下面的内容对它同样适用。

## 跨越线路的 trace {#traces-that-cross-the-wire}

trace 最有用的时候，是它能在一幅连贯的图景里跟随请求从客户端一路进入服务器。

当客户端和服务器都运行本 SDK 时，这种关联是自动的。客户端把 [W3C trace context](https://www.w3.org/TR/trace-context/) 注入请求，服务器再把它读出来，于是服务器 span 嵌套在同一个 trace 的客户端 span 之下。这就是 [SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414)，不用开口就能得到。

如果入站消息没有携带 trace context，比如请求来自一个不是本 SDK 的客户端，服务器 span 就直接以服务器上当前已有的 span 为父，而不是另起一个全新的孤立 trace。

## 关掉它 {#turning-it-off}

追踪是一个中间件，排在服务器中间件列表的第一个。如果确实想要一个不发出任何 span 的服务器，把它拿掉：

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    这个导入带前导下划线，这是故意的。这个类是临时性的，和 [`Server.middleware`](../advanced/middleware.md) 一样是临时性的，所以要预期导入路径会变。你几乎永远用不到这个：没装 exporter 时 span 不花钱，所以通常的做法是让它们开着，不装 exporter 就行。

## 回顾 {#recap}

* 每个 `MCPServer` 和每个低层 `Server` 默认都会为每条入站消息发出一个 `SERVER` span。你什么都不用写。
* span 带有 `mcp.method.name` 和 `mcp.protocol.version`；`tools/call` 和 `prompts/get` 还带有 GenAI 属性，让你的工具调用像其他任何 agent 的一样分组。
* 在安装 OpenTelemetry SDK 和 exporter 之前零成本，装上之后就会亮起来，服务器一行都不用改。
* 两端都运行本 SDK 时，客户端到服务器的 trace context 自动传播。

决定一个请求到底能不能运行的，是 **[授权](authorization.md)**。
