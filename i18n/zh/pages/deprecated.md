---
translation:
  sections: [490237e61c3a7a44, 01262a123ad9501d, 429db5b574a2ac08, e2d0d273fbd2d74b, 64ab0331e868f3d4, 6c8878ce2d1f6d56, 4068f23e371bf0b3, eaef75b8725bc931]
  tool: 1
---
# 已弃用的功能 {#deprecated-features}

2026-07-28 规范让五项内容退役。SDK 仍然实现了其中每一项，而且每一项现在都带有**弃用警告**。另有一个 SDK 辅助函数因自身原因被弃用，列在[本页末尾](#deprecated-sdk-helpers)。

下表列出了每一项已弃用的功能、它为什么要退场，以及应该改用的替代方案。

## 弃用了什么 {#what-is-deprecated}

| 已弃用 | 原因 | 替代做法 |
|---|---|---|
| **根目录（roots）**：`ctx.session.list_roots()`、`client.send_roots_list_changed()`、传给 `Client(...)` 的 `list_roots_callback=` | [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577) 弃用了这一能力。 | 把路径作为普通的工具参数或资源 URI 传入，或者在 `InputRequiredResult` 中嵌入一个 `ListRootsRequest`（见 **[多轮往返（multi-round-trip）请求](handlers/multi-round-trip.md)**）。 |
| **服务器发起的采样（sampling）**：`ctx.session.create_message()`、传给 `Client(...)` 的 `sampling_callback=` | SEP-2577 弃用了这一能力。 | 返回 `InputRequiredResult`，让客户端重试该调用（见 **[多轮往返请求](handlers/multi-round-trip.md)**）。 |
| **协议日志**：`ctx.log()`、`ctx.debug()`、`ctx.info()`、`ctx.warning()`、`ctx.error()`、`ctx.session.send_log_message()`、`client.set_logging_level()` | SEP-2577 弃用了这一能力。协议内没有任何替代。 | 用普通的 `import logging` 输出到 stderr（见 **[日志](handlers/logging.md)**）。 |
| **`ping`**：`client.send_ping()` | 从协议中**移除**，而不仅仅是弃用。2026-07-28 中没有 `ping` 方法。 | 无。它只在 `mode="legacy"` 连接上有效。 |
| **客户端->服务器进度**：`client.send_progress_notification()` | 2026-07-28 规定进度只能由服务器发往客户端。 | 没有什么可发送的。你的**服务器**用 `ctx.report_progress()` 报告进度（见 **[进度](handlers/progress.md)**）。 |

从这张表可以看出三点：

* 根目录、采样和日志是一起的。一份提案 **SEP-2577** 一次性弃用了这三项能力。
* 采样和根目录有一个更深层的共同问题：它们都是**服务器**向**客户端**发送**请求**的地方。2026-07-28 用 **[多轮往返请求](handlers/multi-round-trip.md)** 取代的正是这整个方向。消失的是独立的 RPC 方法（`sampling/createMessage`、`roots/list` 和推送式的 `elicitation/create`）；`CreateMessageRequest` / `ListRootsRequest` / `ElicitRequest` 这些载荷类型保留了下来，嵌入在 `InputRequiredResult.input_requests` 中，在客户端它们触发的还是同样的回调。
* `ping` 是个例外。协议不是弃用它，而是移除它。SDK 的方法仍会发出警告（消息里写的是“removed”，而不是“deprecated”），在现代连接上调用它会得到“Method not found”的回应。

## 弃用只是建议性的 {#deprecated-is-advisory}

今天什么都不会坏。

上面的每个方法在任何协商为 **2025-11-25 或更早版本**的会话上都能继续工作。在客户端固定 `mode="legacy"`，得到的就是 2026 之前的行为，分毫不差。线路上没有任何变化，能力协商也没有变。

变化在于，每个方法第一次运行时你会看到一条醒目的警告：

```text
MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
```

`MCPDeprecationWarning` 继承自 `UserWarning`，而**不是** `DeprecationWarning`。这是有意为之：Python 的默认过滤器只在直接作为 `__main__` 运行的代码中显示 `DeprecationWarning`，库就是这样弃用东西、然后两年都没人注意到的。这个警告到处都会显示，不需要 `-W` 标志。

!!! warning
    “建议性”止于线路。采样和根目录是服务器发往客户端的**请求**，而 2026-07-28 会话没有承载这类请求的通道。在现代连接上的工具里调用 `ctx.session.create_message()`，警告照样触发，然后发送失败并报错：

    ```text
    Cannot send 'sampling/createMessage': this transport context has no back-channel
    for server-initiated requests.
    ```

    两个信号，按这个顺序。`MCPDeprecationWarning` 在你调用方法的那一刻触发，任何连接上都是如此。错误是 SDK 随后尝试发送时返回的结果。这两个功能只有在 `mode="legacy"` 连接上、且客户端注册了对应回调时，才能端到端地工作。

## 旧版会话上的 `ping` {#ping-on-a-legacy-session}

**ping** 是一个空请求，任何一方都可以发送，用来确认对方仍在应答。2026-07-28 规范移除了它（[SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)）：现代客户端发出的每个请求本身就证明服务器在那里，而现代服务器没有通道可以发出 ping。两个 SDK 方法在握手时代的会话上仍然有效。从客户端：

```python
async def main() -> None:
    async with Client("http://localhost:8000/mcp", mode="legacy") as client:
        await client.send_ping()  # warns; returns an EmptyResult
```

从服务器，在任意处理函数内部：

```python
@mcp.tool()
async def check_client(ctx: Context) -> str:
    """A tool that still pings the client mid-call."""
    await ctx.session.send_ping()  # no warning; an EmptyResult while the client is connected
    return "client answered"
```

* `client.send_ping()` 每次调用都会发出 `MCPDeprecationWarning`。在默认（`2026-07-28`）连接上，服务器改为回应 `MCPError: Method not found`。
* `ctx.session.send_ping()` 不带警告。在现代连接上，它和其他任何服务器发起的请求一样，抛出同样的无反向通道（back-channel）错误。
* 双方都不需要注册任何东西来应答 ping。

## 根目录变更通知 {#roots-change-notifications}

声明了根目录能力的 2025 时代客户端，可以发送 `notifications/roots/list_changed` 告诉服务器它的工作区文件夹变了；服务器的回应是再次请求 `roots/list`。2026-07-28 规范把这个通知连同其余推送式的根目录流程一起移除了。在客户端，传入 `list_roots_callback=`（**[客户端回调](client/callbacks.md)**）就等于声明了 `"roots": {"listChanged": true}`，而一次调用就能兑现这个承诺：

```python
async def open_folder(client: Client, uri: str, name: str) -> None:
    """The user opened another folder: expose it through the roots callback, then tell the server."""
    workspace.append(Root(uri=FileUrl(uri), name=name))
    await client.send_roots_list_changed()
```

在服务器端，接收方的处理函数交给低层 `Server`：

```python
async def roots_changed(ctx: ServerRequestContext, params: NotificationParams | None) -> None:
    """The client's roots changed: ask for the new list."""
    roots = (await ctx.session.list_roots()).roots


server = Server("Bookshop", on_roots_list_changed=roots_changed)
```

* `workspace` 是你的 `list_roots_callback` 返回的列表。`client.send_roots_list_changed()` 会发出警告，并且需要 `mode="legacy"` 客户端：在现代连接上，这个通知会被静默丢弃。之后保持会话打开，因为服务器后续的 `roots/list` 请求会从这个会话上到达。
* `MCPServer` 没有针对这个通知的钩子。在低层 `Server` 上，`on_roots_list_changed=` 注册处理函数（它也已弃用，并在构造时发出警告）。通知不带任何载荷，所以处理函数调用 `ctx.session.list_roots()` 获取新列表。

## 屏蔽警告 {#silencing-the-warning}

新代码里不要这样做。

但如果你维护的服务器确实在为 2026 之前的客户端提供服务，它完全有理由要一份安静的日志。在第一个已弃用调用运行之前过滤掉这个类别：

```python
import warnings

from mcp import MCPDeprecationWarning

warnings.filterwarnings("ignore", category=MCPDeprecationWarning)
```

整个 API 就这些。没有按方法的开关，你也不需要：只用一个类别的意义就在于，一行代码让它静音，一行代码把它恢复。

!!! check
    反过来用这个过滤器，就白得一个回归测试。在 pytest 配置的 `filterwarnings` 设置里加上 `"error::mcp.MCPDeprecationWarning"`，已弃用的调用就会**抛出异常**而不是发出警告。一个名为 `old_log`、仍在调用 `ctx.info()` 的工具不再通过：调用返回 `is_error=True`，附带 `Error executing tool old_log`，而捕获到的服务器日志点出了元凶：

    ```text
    mcp.shared.exceptions.MCPDeprecationWarning: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    一行 pytest 配置，已弃用的调用就再也不可能悄悄溜回你的代码库而不让测试失败。

## 已弃用的 SDK 辅助函数 {#deprecated-sdk-helpers}

这些不是规范变更，只是有了更好替代的 SDK 内部实现。它们用同一个 `MCPDeprecationWarning` 发出警告，并将在 3.0 中移除。

| 已弃用 | 替代做法 |
|---|---|
| `FuncMetadata.call_fn_with_arg_validation()` | 先调用 `FuncMetadata.validate_arguments()`，再调用 `FuncMetadata.call_fn()`。只有直接驱动 `FuncMetadata` 的代码（比如自定义的 `Tool` 子类）才调用过它。 |

## 回顾 {#recap}

* 2026-07-28 规范弃用了**根目录**、服务器发起的**采样**和协议**日志**（都出自 [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)），把**进度**限制为只能由服务器发往客户端，并移除了 **`ping`**。
* 替代做法那一列为你指明了去处：采样和根目录看 **[多轮往返请求](handlers/multi-round-trip.md)**，日志看 **[日志](handlers/logging.md)**，进度看 **[进度](handlers/progress.md)**。`ping` 什么都不需要。
* 弃用只是建议性的：线路上没有变化，在 2026 之前的会话上一切照常工作，你会看到一条醒目的 `MCPDeprecationWarning`（它是 `UserWarning`，所以默认开启）。
* 采样和根目录还需要一条反向通道，而 2026-07-28 会话没有。在现代连接上，它们先警告，然后抛出异常。
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` 让整个类别静音；pytest 中的 `"error::mcp.MCPDeprecationWarning"` 把它变成测试失败。
* 一个 SDK 辅助函数 `FuncMetadata.call_fn_with_arg_validation()` 单独被弃用，将在 3.0 中移除。
* 新代码不应建立在其中任何一项之上。

本文档的其他每一页讲的都是当前的 API。
