---
translation:
  sections: [cfe01c0c5863dfa2, 11d93f1fa09eadf5, a7392996acf1ad8f, 875eb2889263424e]
  tool: 1
---
# v2 的新变化 {#whats-new-in-v2}

v2 里同时发生了两件事。一是 **SDK 重建了**：客户端和服务器底下都换了新引擎，`Client` 成了一等公民，还有一批重命名，v1 代码库在第一次 import 时就会碰上。二是 **协议变了**：v2 讲的是 MCP 的 2026-07-28 修订版，这一版去掉了连接握手、会话和所有由服务器发起的请求，同时不会抛下你已有的客户端。

本页把这两半都带你过一遍，每个要点一节，每节末尾指向专门讲该主题的页面。它不是移植手册。移植手册是 **[迁移指南](migration.md)**：每一项破坏性变更，附改动前后的代码。

!!! note "v2 是稳定版本"
    `pip install mcp` 安装的是 2.x，**[安装](get-started/installation.md)** 里有可以直接复制粘贴的安装命令。如果 v2 里有什么东西坏了、让你意外或者拖慢了你，请[告诉我们](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

## SDK：从 v1 到 v2 {#the-sdk-v1-to-v2}

### `FastMCP` 现在叫 `MCPServer` {#fastmcp-is-now-mcpserver}

高层服务器类改了名，它所在的模块也一起改了。这是每个 v1 服务器碰到的第一件事，因为旧的 import 路径是直接没了，而不是标记为已弃用：

```python
from mcp.server import MCPServer  # v1: from mcp.server.fastmcp import FastMCP

mcp = MCPServer("Demo")  # v1: FastMCP("Demo")
```

对用装饰器构建的服务器来说，这也就是移植工作的大头。`@mcp.tool()`、`@mcp.resource()` 和 `@mcp.prompt()` 接受的东西和 v1 一样（`@mcp.resource()` 多了一个可选的 `security=` 关键字参数），输入模式仍然来自你的类型提示。边边角角的地方：`mcp.server.fastmcp.*` 下的所有内容现在都在 `mcp.server.mcpserver.*` 下，`ctx.fastmcp` 变成了 `ctx.mcp_server`，`get_context()` 没有了（改为声明一个 `ctx: Context` 参数），异常基类 `FastMCPError` 变成了 `MCPServerError`。import 对照表见 **[迁移指南](migration.md#fastmcp-renamed-to-mcpserver)**。

### `Resolve`：向用户索要输入的新方式 {#resolve-the-new-way-to-ask-the-user-for-input}

工具需要的东西并不都该由模型提供。v2 新增：用 `Resolve(fn)` 注解的工具参数改由你写的函数来填充，模型看不到它，而这个函数可以返回 `Elicit(...)`，把一个问题摆到用户面前。这是在调用中途从客户端获取任何东西的首选方式：SDK 会通过连接所支持的机制把问题送过去——对旧版客户端是一次实时的征询（elicitation）请求，在 2026-07-28 上是一次多轮往返（multi-round-trip）——所以同一个工具函数体同时适用于新旧两代协议。详见 **[依赖](handlers/dependencies.md)**。

!!! note
    另外两种形式在需要时仍然可用：对旧版连接上的客户端，`ctx.elicit()` 照样能用（**[征询](handlers/elicitation.md)**）；处理函数也可以自己返回 `InputRequiredResult` 并手动驱动各轮往返，这也是 2026-07-28 上采样（sampling）和根目录（roots）请求的传递方式（**[多轮往返请求](handlers/multi-round-trip.md)**）。

### 一等公民 `Client` {#a-first-class-client}

v1 交给你的是三层嵌套：一个产出原始流的传输上下文管理器，包在外面的 `ClientSession`，再加上手动调用的 `await session.initialize()`。v2 只有一个对象：

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

`Client` 接受一个服务器对象（内存直连，没有传输：这就是测试的做法）、一个 URL（Streamable HTTP），或者任意传输上下文管理器，比如 `stdio_client(...)`。进入 `async with` 就会建立连接并协商协议版本，不管服务器讲的是哪一代协议；之后 `client.server_capabilities` 和 `client.protocol_version` 直接就在那里，服务器表明身份时 `client.server_info` 也一样（它现在是 `Implementation | None`，因为 2026 版的身份信息是可选的）。你在 v1 注册的采样和征询回调仍然能用（它们的函数体会看到和本页其他地方一样的 snake_case 属性重命名），现在还会回答 2026 风格的、嵌在结果里的请求（见下文），并且是并发运行而不是一次一个。想要底层接口的人仍然可以用底下的 `ClientSession`，`client.session` 会把它交给你；它也变了（运行在新的调度器引擎上，自身的一些签名也改了），所以下探之前先读 **[迁移指南](migration.md#clientsession-now-runs-on-jsonrpcdispatcher-basesession-removed)**。

**[Client](client/index.md)** 介绍它，**[客户端传输](client/transports.md)** 讲三种连接形式，**[客户端回调](client/callbacks.md)** 讲回调本身，**[测试](get-started/testing.md)** 展示取代 v1 `create_connected_server_and_client_session()` 辅助函数的内存模式。

### 底层 `Server` 是重建，不是改名 {#the-low-level-server-was-rebuilt-not-renamed}

如果你在 JSON-RPC 层工作，这就是 v2 里“什么都不一样了”的那部分。下面是同一个单工具服务器的两种写法；点击标记查看哪些东西变了。

<!-- The v1 fence cannot be a tested docs_src file (nothing in CI can import the
1.x SDK). Its ground truth: this exact code was run verbatim against a real
mcp==1.28.1 install. If you edit it, re-validate it against 1.x. -->

```python title="v1"
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server

server = Server("Bookshop")


@server.list_tools()  # (1)!
async def list_tools() -> list[types.Tool]:
    return [  # (2)!
        types.Tool(
            name="search_books",
            description="Search the catalog by title or author.",
            inputSchema={  # (3)!
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.ContentBlock]:  # (4)!
    if name != "search_books":
        raise ValueError(f"Unknown tool: {name}")  # (5)!
    ctx = server.request_context  # (6)!
    return [types.TextContent(type="text", text=f"Found 3 books matching {arguments['query']!r}.")]  # (7)!
```

1. 处理函数用装饰器注册（装饰器要调用，带括号），服务器创建之后随时都可以。
2. 返回一个裸的 `list[Tool]`，SDK 会把它包成 `ListToolsResult`。
3. 字段在 Python 里是 camelCase，而且模式 **会被强制执行**：SDK 在你的函数运行之前用 jsonschema 按它校验 `call_tool` 的参数，所以下面的 `arguments["query"]` 是安全的。
4. 一个 `call_tool` 处理函数服务所有工具，它收到的是工具名和已经校验过的参数，已解包，且永远不会是 `None`。
5. v1 工具用抛异常来表示失败：任何异常都会被捕获并作为 `CallToolResult(isError=True)` 返回，文本是 `str(e)`，所以发起调用的模型能读到这条消息并可以重试。
6. 上下文来自一个环境 ContextVar，在请求处理中途通过服务器对象拿到。
7. 裸的内容块会替你包成 `CallToolResult`。

```python title="v2"
--8<-- "docs_src/whats_new/tutorial001.py"
```

1. 字段现在是 snake_case，而模式 **只对外公布、从不实际应用**：处理函数运行之前没有任何东西检查参数。
2. 每个处理函数的形状都一样：`async (ctx, params) -> result`。上下文是第一个参数（`ctx.session`、`ctx.request_id`、`ctx.protocol_version` 都在它上面）；`server.request_context` 就是搬到了这里。
3. 完整的 `ListToolsResult` 由你自己构建。现在返回裸列表会在服务器端得到 `TypeError`，SDK 不会再替你包装。
4. 进来的是带类型的 params（`params.name`、`params.arguments`），出去的是完整的结果。没有任何东西替你解包、包装或转换。
5. 同样的检查，抛出的异常不同。这里抛 `ValueError` 会以一个不透明的 `-32603` 到达模型（见下文），所以要故意返回线路错误就抛 `MCPError`：它会带着自己的错误码和消息原样穿过去，而带这段文本的 `-32602` 正是规范自己对未知工具给出的答复。
6. `params.arguments` 可能是 `None`；v1 会在你的代码看到它之前把它默认成 `{}`。处理函数前面没有校验了，所以这一行必不可少。
7. 这里抛出的意外异常会变成一个 **脱敏后的** 协议错误，`-32603` `"Internal server error"`：模型永远看不到那条消息。对于模型应该读到并做出反应的失败，返回 `CallToolResult(is_error=True, ...)`。
8. 处理函数是构造函数参数，所以服务器一创建出来，它的接口就已经完整；`add_request_handler()` 是构造之后的应急出口，也是通往自定义方法的入口。

这个例子就是模式本身。更一般地说：每个处理函数的形状都一样，带类型的 params 进来，完整的结果类型出去；以前对工具参数的 jsonschema 检查没有了；异常就是协议错误，永远不会是 `is_error=True` 的工具结果；环境里的 `server.request_context` ContextVar 也没有了。带厂商命名空间的自定义方法通过 `add_request_handler(method, params_type, handler)` 成为一等公民，它会在处理函数运行之前按你的模型校验入站 params。另外还有一个 `middleware` 列表（特意标记为暂定）包裹每一条入站消息，取代了以前人们去重写的私有 `_handle_*` 方法。

在底层，v1 的 `BaseSession` 接收循环换成了一个调度器引擎，客户端和服务器现在共用它，本页上好几件事能同时成立靠的就是它：同一个 `Server` 对象同时服务两代协议，`Client(server)` 在进程内直接分发、没有 JSON-RPC 封帧，客户端请求超时现在会真的取消服务器端的处理函数。

详见 **[底层 Server](advanced/low-level-server.md)**；**[迁移指南](migration.md#lowlevel-server-decorator-based-handlers-replaced-with-constructor-on_-params)** 逐一讲解每个被移除的钩子。如果你从没下探到 `MCPServer` 以下，这些都不影响你。

### 线路类型搬到了 `mcp-types`，每个字段都是 snake_case {#the-wire-types-moved-to-mcp-types-and-every-field-is-snake_case}

协议类型现在有了自己的发行包 `mcp-types`。它除了 pydantic 和 typing-extensions 之外什么都不依赖，所以网关、代理或代码生成器不用安装 HTTP 栈就能使用 MCP 的线路结构：这样的项目安装 `mcp-types`，然后 import `mcp_types`。`mcp` 本身以精确版本依赖那个包并把它重新暴露出来，所以依赖 SDK 的代码继续写 `import mcp.types as types` 和 `from mcp.types import Tool`（永久别名，每个名字都是同一个对象），并且只声明它唯一真正的依赖 `mcp`。经验法则：通过你实际依赖的那个包来 import。

在这些类型上，每个 Python 属性现在都是 snake_case：`result.is_error`、`tool.input_schema`、`listing.next_cursor`。线路上的 JSON 仍然是 camelCase，和以前完全一样；变的只是属性的拼写。同时附带两个更严格的默认行为：未知字段会被忽略而不是原样往返（额外的东西放进 `_meta`），并且两端都会按协商好的协议版本校验流量。重命名对照表见 **[迁移指南](migration.md#field-names-changed-from-camelcase-to-snake_case)**。

### 传输配置搬到了 `run()` {#transport-configuration-moved-to-run}

`MCPServer(...)` 关心的是你的服务器 **是什么**：它的名称、instructions、生命周期、认证。至于它 **怎样对外提供服务**，现在归 `run()` 和应用构建函数管，`host`、`port`、`stateless_http`、`json_response`、端点路径和 `transport_security` 都搬到了那里（`MCPServer("x", port=9000)` 会得到 `TypeError`）。各个重载按传输方式分别标注了类型，所以编辑器会告诉你 `stdio` 接受哪些选项、`streamable-http` 接受哪些。有一处移除值得知道：`mount_path` 没有了；要在某个前缀下提供服务，受支持的做法是挂载 ASGI 应用。

选项见 **[运行服务器](run/index.md)**；挂载见 **[添加到现有应用](run/asgi.md)**。

### 行为变了但不会报 import 错误的地方 {#behavior-that-changes-without-an-import-error}

重命名会自己跳出来提醒你。下面这些不会：

* **同步函数在工作线程上运行。** `def` 定义的工具（或资源、提示词、解析器）不再阻塞事件循环；代价是它的函数体不再 **在** 事件循环线程上运行，这对有线程亲和性的代码有影响。`async def` 处理函数不受影响。**[迁移指南](migration.md#sync-handler-functions-now-run-on-a-worker-thread)**。
* **在工具内部抛出的 `MCPError`（v1 的 `McpError`）现在是协议错误。** 模型永远看不到它。其他所有异常仍然会变成模型能读到并做出反应的 `is_error=True` 结果。两者的划分见 **[错误处理](servers/handling-errors.md)**。
* **结果在发出之前会被校验。** 手工构建的 `Tool` 如果 `input_schema` 是 `{}`，现在会让 `tools/list` 失败（规范要求 `"type": "object"`）。基于 `@mcp.tool()` 构建的服务器永远不会遇到这个；它们的模式是 SDK 写的。
* **你的客户端会校验收到的东西。** `list_tools()` 和 `call_tool()` 会按协商好的协议版本检查服务器的答复，所以 v1 宽松解析能容忍的不太合规的服务器，现在会抛 `pydantic.ValidationError`。如果你连接的是自己不控制的服务器，要做好由你来发现它们的准备；细节见 **[迁移指南](migration.md#client-validates-inbound-traffic-against-the-protocol-schema)**。
* **URI 模板现在是真正的 RFC 6570。** `{+path}`、`{?query}` 之类都能用，匹配是精确的而不是正则式的宽松匹配，提取出的值里的路径穿越默认会被拒绝。更严格的模板在装饰时就失败，而不是等到第一个请求。**[URI 模板](servers/uri-templates.md)**。
* **Streamable HTTP 的生命周期只运行一次**，在启动时运行，它的状态由所有会话和请求共享。在 v1 里它每个会话运行一次，`stateless_http=True` 下则是每个请求一次。在生命周期里建的连接池和缓存会便宜得多；以前在那里获取每连接资源的做法，现在应该放进处理函数体里。**[生命周期](handlers/lifespan.md)**。
* **`mcp dev` 和 `mcp install` 会把它们启动的环境固定** 到你已安装的 SDK 版本。这两个命令在一个全新的 `uv run --with ...` 环境里运行你的服务器，以前这个环境会把 `mcp` 解析成最新的稳定版，而不是你开发所针对的版本。**[迁移指南](migration.md#mcp-dev-and-mcp-install-pin-the-spawned-environment-to-your-sdk-version)**。
* **HTTP 客户端现在是 `httpx2`，不是 `httpx`。** 这次依赖替换改变了你的代码要捕获和传递的东西（`httpx2.AsyncClient`、`httpx2.ConnectError`），也改变了 TLS 证书的校验方式：`httpx2` 通过 `truststore` 按操作系统的信任库校验，而不是 certifi 自带的 CA 列表。大多数环境根本察觉不到；没有系统 CA 库的极简容器，或者只有 certifi 的证书包才认识的私有 CA，会开始在 TLS 握手时失败。设置 `SSL_CERT_FILE`/`SSL_CERT_DIR`，或者给客户端传 `verify=ssl_context`。**[迁移指南](migration.md#httpx-and-httpx-sse-replaced-by-httpx2)**。

### 彻底移除的内容 {#removed-outright}

下面每一项在 **[迁移指南](migration.md)** 里都有一节：

* **WebSocket 传输**，两端都是，以及 `mcp[ws]` extra。它从来不是 MCP 规范的一部分。
* **实验性的 Tasks** API（`mcp.*.experimental`）。2026-07-28 把任务从核心协议里移出去，放进了一个官方扩展（[SEP-2663](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2663)），本 SDK 尚未实现它。
* 作为 import 路径的 `mcp.shared.version`、`mcp.shared.progress` 和 `mcp.shared.session`（连同 v1 `message_handler` 注解会 import 的 `RequestResponder` 桩）。（`mcp.types` **没有** 被移除：它作为独立 `mcp_types` 包的永久别名保留。）
* 已弃用的 `streamablehttp_client` 拼写，以及 `streamable_http_client` 的 `get_session_id` 回调（它现在恰好产出两个流）。
* `McpError`，改名为 **`MCPError`**，带一个直接的 `(code, message, data)` 构造函数。
* `MCPServer.get_context()`、`mount_path=`，以及底层 `Server` 的装饰器方法、ContextVar 和处理函数字典。

## 协议：从 2025-11-25 到 2026-07-28 {#the-protocol-2025-11-25-to-2026-07-28}

v2 实现了 2026-07-28 修订版，并且同时服务 **两个** 修订版：同一个 `streamable_http_app()`（以及同一个 stdio 服务器）既回答 2025 版客户端的 `initialize`，也回答 2026 版客户端的请求，不需要配置任何东西，不需要开什么开关，也不需要单独部署。服务新修订版不会抛下还在旧版上的客户端。下面讲的是新修订版本身改变了什么。

### 没有握手，没有会话 {#no-handshake-no-session}

2026-07-28 的客户端不会先打开连接、协商、然后再说话。每个请求都在 `_meta` 里携带自己的协议版本、客户端信息和客户端能力，而唯一的发现调用 `server/discover` 也是和其他请求一样的普通请求。`Client` 默认就会做正确的事：它探测一次 `server/discover`，如果服务器比较旧，就回退到 `initialize` 握手。

在 Streamable HTTP 上，2026 路径没有 `Mcp-Session-Id`，这是运维层面的头条：**没有任何东西把新版请求绑在某个工作进程上**，所以普通轮询负载均衡器后面的任何副本都能回答它。有两点要如实说明。你的 2025 版客户端（今天来说，也就是大多数客户端）仍然会打开会话，仍然需要它们在 v1 上需要的那种会话粘滞；对它们来说什么都没变。而 **多轮往返** 重试唯一需要跨工作进程携带的东西是它密封好的 `request_state`，它的默认密钥是每个进程各自生成的，所以横向扩展的部署要传入 `RequestStateSecurity(keys=[...])`。（`stateless_http=True` 与此无关：它只影响 2025 版客户端如何被服务，2026 的流量从不读取它；如果你在 v1 里已经设置了它，什么都不变。）

这件事的客户端一侧见 **[协议版本](protocol-versions.md)**，运维人员的检查清单见 **[部署与扩展](run/deploy.md)**（Host 允许列表、`request_state` 密钥、跨副本的通知），同时服务两代协议的做法见 **[服务旧版客户端](run/legacy-clients.md)**。

### 服务器不能调用客户端：多轮往返请求 {#the-server-cannot-call-the-client-multi-round-trip-requests}

在 2026-07-28 上，所有由服务器发起的请求都没有了：推送式征询、采样、`roots/list`。2026 连接上没有给它们用的通道，所以 `ctx.elicit()` 和 `ctx.session.create_message()` 在那里会以 `NoBackChannelError` 失败（对旧版客户端它们仍然能用）。

替代方案把调用反了过来。需要从用户那里拿东西的工具把问题 **返回** 出去（`InputRequiredResult`），客户端用它一直都有的那些回调来回答，然后调用会带着答案重试。`Client` 替你驱动这个循环。在服务器上你很少自己构建这个结果，因为 **[依赖](handlers/dependencies.md)** 会做这件事：用 `Resolve(ask_quantity)` 注解一个参数，其中 `ask_quantity` 是你写的普通函数，SDK 就会通过连接所支持的机制去问——在旧版会话上是实时的征询请求，在 2026 上是多轮往返。一个工具函数体，两代协议：

```python title="dual_era.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

这个文件把卖点集中在了一处：一个服务器，一个由 `Resolve` 支撑的工具，一个旧版客户端加一个新版客户端都拿到了各自的答案，全在内存里。**[多轮往返请求](handlers/multi-round-trip.md)** 解释这个机制（包括 `request_state`，SDK 会替你密封并验证它）；**[征询](handlers/elicitation.md)** 讲提问的部分。

!!! warning "这是移植过来的 v1 服务器唯一会改变行为的地方"
    你自己的测试会最先碰到它：`Client(mcp)` 默认会和你的 v2 服务器协商出 2026-07-28，所以调用 `ctx.elicit()` 的工具会在一个 v1 上能通过的测试里失败。把问题挪进一个 `Resolve(...)` 参数（两代通用），或者如果你确实想要推送行为，就把测试客户端固定为 `mode="legacy"`。

### 根目录、采样和协议日志已弃用；`ping` 已移除 {#roots-sampling-and-protocol-logging-are-deprecated-ping-is-removed}

[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) 弃用了整整三项 **能力**，而且是在所有协议版本上：根目录、采样和 MCP 层面的日志（`ctx.info()` 之类）。这和上面缺少反向通道（back-channel）是两个不同的维度；弃用只是建议性的，针对 2025 版会话一切照常工作，线路上没有任何变化。你会注意到的是 `MCPDeprecationWarning`，它是一个 `UserWarning`，所以默认会打印出来；升级之后你的第一个 `ctx.info(...)` 大概就会这么说。

`ping` 更严格：是从协议里移除，不是弃用。已弃用功能里有两个独立方法在 2026-07-28 也同样被移除，`logging/setLevel` 和客户端的 `notifications/roots/list_changed`，而进度通知现在只能从服务器发往客户端。

完整的表格、每一项的替代方案，以及在服务旧版客户端期间想让日志安静下来时用的那一行过滤器，都见 **[已弃用功能](deprecated.md)**。

### 变更通知合并为一条流 {#change-notifications-become-one-stream}

在 2026-07-28 上，独立的 HTTP GET 流和 `resources/subscribe` 被 `subscriptions/listen` 取代：客户端打开一条长连接流，并指明它想要的通知种类。`MCPServer` 默认就能服务它；用 `await ctx.notify_resource_updated(uri)`（以及 `notify_tools_changed()` 等等）来发布，中间件可以按调用方拒绝某个 listen 请求，多副本部署则接入一个共享的 `SubscriptionBus`。在客户端，`async with client.listen(...)` 打开这条流：过滤条件以关键字参数传入，带类型的变更事件传回来，`sub.honored` 是服务器同意投递的那个子集。

发布和服务见 **[订阅](handlers/subscriptions.md)**，监听一端见 **[客户端部分的姊妹篇](client/subscriptions.md)**，总线见 **[部署与扩展](run/deploy.md)**。

### 其余变化速览 {#the-rest-quickly}

* **身份信息是可选的、按消息携带的元数据。** 请求侧的 `clientInfo` `_meta` 键是可选的（必需的一对是 `protocolVersion` + `clientCapabilities`），`serverInfo` 则从 `server/discover` 的结果体里搬了出来：服务器改为把它盖进每个 2026 版结果的 `_meta` 里（[规范 #3002](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/3002)）。SDK 总是会盖；服务器不表明身份时（比如某个中间件剥掉了这个键），`client.server_info` 就是 `None`。**[底层 Server](advanced/low-level-server.md)** 展示了线路上的这个印记。
* **请求不用解析请求体就能路由。** 新版 HTTP 请求带有 `Mcp-Method`（对三个类似工具的调用，还有 `Mcp-Name`）；用 `x-mcp-header` 注解的工具输入模式属性会被镜像成一个 `Mcp-Param-*` 头，并由服务器交叉核对（[SEP-2243](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2243)）。网关和限流器单凭请求头就能路由；规则见 **[迁移指南](migration.md#servers-validate-mcp-param-headers-against-the-request-body-sep-2243)**。
* **结果带有缓存提示。** 列表和读取结果声明 `ttlMs` 和 `cacheScope`（[SEP-2549](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2549)）；用 `cache_hints=` 按方法设置它们，`Client` 则用内置的响应缓存来遵守它们。不发送提示的服务器（所有 2026 之前的服务器）看到的是完全相同、未经缓存的流量。**[缓存提示](client/caching.md)**。
* **扩展是一等公民。** 服务器和客户端在反向 DNS 标识符下声明可选的能力包（[SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)）；内置的 `Apps` 扩展（MCP Apps）是参考实现。**[扩展](advanced/extensions.md)** 和 **[MCP Apps](advanced/apps.md)**。
* **错误码标准化了。** 不存在的资源是 `-32602`，URI 放在 `error.data` 里，新的规范保留码有 `-32020`（头不匹配）、`-32021`（缺少必需的能力）和 `-32022`（不支持的协议版本）。**[故障排查](troubleshooting.md)** 按确切的消息文本编排。
* **授权更难用错了。** 客户端会校验随授权码返回的 `iss`（[RFC 9207](https://datatracker.ietf.org/doc/html/rfc9207)；你的 `callback_handler` 现在返回一个 `AuthorizationCodeResult`），注册时会发送 `application_type`，并且永远不会把凭据重放给另一个授权服务器。企业场景的新东西：[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 身份断言流程。**[迁移指南](migration.md)** 列出了每一项 OAuth 变更；相关页面是 **[客户端 OAuth](client/oauth-clients.md)** 和 **[身份断言](client/identity-assertion.md)**。
* **每个服务器都可追踪。** OpenTelemetry 作为中间件默认开启：每个请求都有一个服务器 span，在进程配置 exporter 之前没有任何开销。两端都运行本 SDK 时，客户端还会在 `_meta` 里传播 W3C trace context，所以两边的 trace 能接上。**[OpenTelemetry](run/opentelemetry.md)**。

## 要从 v1 升级？ {#upgrading-from-v1}

* **[迁移指南](migration.md)** 是完整、精确的改动清单；本页讲的是为什么。
* **v1.x 不会消失。** 它转入维护状态，继续获得关键修复和安全补丁，2026-07-28 规范的发布不会破坏它的任何东西；它的文档在 [/v1/](https://py.sdk.modelcontextprotocol.io/v1/)。如果你发布了一个依赖 `mcp` 的库而且还没准备好迁移，保留一个版本上限（比如 `mcp>=1.28,<2`），这样未固定版本的解析就会停留在 1.x。
* 有什么粗糙、让人困惑或者坏掉的地方？**[提交 v2 反馈](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)**；每一条都会有人读。
