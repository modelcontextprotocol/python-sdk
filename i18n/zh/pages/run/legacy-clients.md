---
translation:
  sections: [3d1663c18edc824c, d4fd37009a13f03d, af9f398a5a8b679a, 470c2dd144294d69, 8e45827e6d24e8c8, 91dfd0ce98ebb03c]
  tool: 1
---
# 服务旧版客户端 {#serving-legacy-clients}

MCP 有两个协议时代：`initialize` 握手时代（到规范版本 `2025-11-25` 为止）和现代时代（`2026-07-28`）。**[协议版本](../protocol-versions.md)** 专门讲这一划分本身。

本页讲的是这一划分的服务器端，答案一句话就能说完：**你已经部署的 `streamable_http_app()` 同时服务两者。**

SDK 按 `MCP-Protocol-Version` 头路由每个请求。声明 `2026-07-28` 的请求交给现代一侧处理。声明握手时代版本的请求，或者根本不带这个头的请求（2026 之前的客户端的 `initialize` 就是这样到达的），则走这些客户端期望的传输方式：`initialize` 握手、会话，一应俱全。这一切按请求发生，在你的代码之前，就在这一个应用上。

所以旧版客户端不是你要**专门为之**构建什么的对象，而是会**连接到**你已经写好的服务器的东西。什么都不用配置。

!!! note
    真的什么都没有。没有 `legacy=` 选项，没有版本白名单，也没有办法拒绝或禁用某个时代：`streamable_http_app()` 上没有，`run()` 上没有，会话管理器上也没有。两个时代始终开启。那个签名里最接近按时代开关的东西是 `stateless_http`，本页大部分内容都在讲它。

## 一个处理函数，两个时代 {#one-handler-both-eras}

下面是一个需要向用户提问的工具，以及两个时代的客户端分别调用它：

```python title="server.py" hl_lines="24 37-38"
--8<-- "docs_src/legacy_clients/tutorial001.py"
```

`reserve` 需要一样模型没有提供的东西：要几本。工具用 `Annotated[..., Resolve(ask_quantity)]` 来声明这一点（详见 **[依赖](../handlers/dependencies.md)**）。`reserve` 里没有任何地方提到版本、检查能力或做分支。

两个客户端**同时**打开，连的是同一个 `mcp` 对象。`mode="legacy"` 会执行 `initialize` 握手：这正是 2026 之前的客户端打开的那种连接。另一个取默认值，落在 `2026-07-28` 上。

```text
2025-11-25 {'result': "Reserved 2 of 'Dune'."}
2026-07-28 {'result': "Reserved 2 of 'Dune'."}
```

同一个服务器，同一个处理函数，同一个答案。整个功能就是这样。

值得停下来看看它是**怎么**做到的，因为这两个客户端是在两条完全不同的线路上被问到同一个问题的。`2026-07-28` 连接没有供服务器发送请求的通道，所以 `Resolve` 把问题放在工具结果里返回，客户端带着答案重试了这次调用（**[多轮往返（multi-round-trip）请求](../handlers/multi-round-trip.md)**）。`2025-11-25` 连接没有这种机制；在那里，`Resolve` 在调用中途发出一个实时的 `elicitation/create` 请求并等待。两种你都没写。`Resolve` 读取连接协商出的版本并做选择；无论哪种，工具函数体看到的都是一个 `AcceptedElicitation`。

!!! tip
    这种跨时代可移植性正是应该基于 `Resolve` 这个 API 来构建的**原因**。它的前辈 `ctx.elicit()`（**[征询（elicitation）](../handlers/elicitation.md)**）永远只发送 `elicitation/create`，所以永远只在旧版连接上有效。在 `2026-07-28` 连接上这个调用会失败。如果某个工具还在用它，修复办法就是上面看到的那样，而不是加版本检查。

## 旧版会话的代价 {#what-a-legacy-session-costs-you}

路由是免费的，会话不是。

`2026-07-28` 连接是**无会话**的：每个请求各自独立，现代一侧从不签发 `Mcp-Session-Id`。旧版连接正好相反。2026 之前的客户端一发送 `initialize`，SDK 就会生成一个 `Mcp-Session-Id`，在响应头里返回，并在它背后保留一条活的记录，供该客户端之后的请求查找：协商出的版本、打开的流、一个驱动会话的后台任务。

这条记录就是一个**普通的进程内 `dict`**。没有分布式会话存储，也没办法接入一个。

只有一个 worker 时这一点看不出来。有两个时，它就是全部问题所在：一个带着 `Mcp-Session-Id` 的请求落到没有生成它的 worker 上，在那个 dict 里什么也找不到，得到的回答是 `404`（`Session not found`），而不是工具结果。所以一旦运行多于一个 worker，**旧版客户端就需要粘性路由**：会话里的每个请求都必须到达发起这个会话的那个进程。现代客户端从不需要；它们没有会话可粘。**[部署与扩展](deploy.md)** 讲了粘性以及运行多个实例的其他一切。

!!! warning
    `event_store=` 看起来像是解决办法，其实不是。它是**可恢复性**（向重连到**同一个**会话的客户端重放错过的 SSE 事件），不是会话存储。它永远不会让一个会话能从另一个进程访问到。

## 唯一的开关：`stateless_http` {#the-one-knob-stateless_http}

如果粘性是你不愿付的代价，那么恰好有一样东西可以改。

```python title="server.py" hl_lines="28"
--8<-- "docs_src/legacy_clients/tutorial002.py"
```

这就是页面开头的那个服务器，加上一个关键字参数。`stateless_http=True` 让旧版这一路改为每个请求建一个用完即弃的会话：不签发 `Mcp-Session-Id`，请求之间什么都不记，所以任何 worker 都能服务任何请求，负载均衡器想怎么分就怎么分。

关于它，有两点比它做了什么更重要。

**它只影响旧版这一路。**请求在读取 `stateless_http` **之前**就已经按版本头路由了，所以现代路径根本看不到它。`2026-07-28` 连接本来就是无会话的，两种取值下完全一样。

**它会让这一路失去两条服务器到客户端的通道。**只活一个 `POST` 的会话，没有供服务器推送请求的流，也没有供它推送通知的独立流。每个服务器发起的请求都会抛出 `NoBackChannelError`：`ctx.elicit()`、已退役的采样（sampling）和根目录（roots）调用（**[已弃用的功能](../deprecated.md)**），以及——没错——`Resolve` 向**旧版**客户端提问。通知连错误都没有；它们被悄悄丢弃。

!!! note
    `json_response=True` 不是那个开关，但它在**每一个**旧版会话上都要付一半同样的代价：用一个 JSON 正文回答的 `POST` 没有供请求范围通道使用的流，所以请求中途的 `ctx.elicit()` 会抛出同样的 `NoBackChannelError`，与该请求绑定的通知会被丢弃。会话的独立流不受影响：无关的通知仍然能到达。

!!! check
    故意做错一次。`reserve` 就是刚才同时服务两个客户端的那个工具。用 `stateless_http=True` 部署它，通过 HTTP 连上同样的两个客户端，分别调用它。

    现代客户端仍然收到 `Reserved 2 of 'Dune'.`，现代这一路没变。

    旧版客户端的调用不会以模型能读到的 `is_error` 结果返回。整个请求失败了，是一个顶层协议错误：

    ```text
    mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
    ```

    `Resolve` 没能救你。在 `2025-11-25` 连接上它**必须**发送 `elicitation/create`，而它需要的通道正是 `stateless_http=True` 放弃掉的东西。跨时代可移植的代码不等于不需要反向通道（back-channel）的代码。

所以这是一个实实在在的取舍，而且只存在于旧版这一路：**有会话且粘性，或者无状态且单向。**如果你的工具从不回调客户端，`stateless_http=True` 就是免费的，应该用它。如果会回调，就保留会话，保持路由粘性。

## 你的代码真正分叉的地方 {#where-your-code-actually-forks}

几乎没有。

工具、资源、提示词、结构化输出、进度、错误：它们都不在乎是哪个时代调用的。`initialize` 握手、`Mcp-Session-Id`、独立流、结束会话的 `DELETE`：全归 SDK 管，处理函数一个都看不到。交互式输入是两个时代在线路上**真正**不同的地方，而 `Resolve` 的存在就是为了让它不成为你的问题：你刚刚看过一个工具同时服务两者。

只剩下恰好一件事，就是**变更通知**，因为两个时代在不同的管道上监听：

* `2026-07-28` 客户端打开一个 `subscriptions/listen` 流并读取订阅总线。`ctx.notify_resource_updated()`（以及 `notify_tools_changed()`、`notify_prompts_changed()`、`notify_resources_changed()`）发布到那里，而且**只**发布到那里。详见 **[订阅](../handlers/subscriptions.md)**。
* 旧版客户端读取它的会话保持打开的独立流。`ctx.session.send_resource_updated()`（以及 `send_tool_list_changed()` 等）写入承载这次请求的**连接**：对旧版会话来说，就是它的独立流。现代连接没有地方放它：通过 HTTP 没有这样的通道，通过 stdio 这四类变更通知只走 `subscriptions/listen` 流，所以在现代连接上这条通知会被悄悄丢弃。

通过 HTTP，两个调用都到不了另一个时代的客户端。要通知所有人，两个都调用：

```python title="server.py" hl_lines="19-20"
--8<-- "docs_src/legacy_clients/tutorial003.py"
```

两行，没有 `if`，没有版本检查，就完事了。因为旧版客户端存在而让处理函数做法不同的事情，全部清单就这些。

## 回顾 {#recap}

* 一个 `streamable_http_app()` 服务两个协议时代。SDK 按 `MCP-Protocol-Version` 头路由每个请求；没有什么要配置，也没有什么时代开关可找。
* 旧版客户端的代价是一个会话：一条进程内的 `Mcp-Session-Id` 记录，背后没有分布式存储。多于一个 worker 就意味着**粘性路由**，否则错的 worker 会回答 `404 Session not found`。多 worker 的情况详见 **[部署与扩展](deploy.md)**。
* `stateless_http=True` 是唯一的开关，而且**只作用于旧版这一路**。它为旧版客户端换来自由的负载均衡，代价是这一路上两条服务器到客户端的通道：服务器发起的请求抛出 `NoBackChannelError`（在客户端是顶层错误，不是 `is_error` 结果），通知被丢弃。
* `2026-07-28` 连接无论如何都是无会话的。`stateless_http` 永远碰不到它。
* 处理函数代码只在恰好一个地方按时代分叉：变更通知。`ctx.notify_*` 送达 `subscriptions/listen` 客户端；`ctx.session.send_*` 送达旧版会话。两个都调用。
* 其他一切（包括通过 `Resolve` 向用户要输入）在构造上就是跨时代可移植的。把现代的写法写一次就够了。
