---
translation:
  sections: [20541a40dbdd5980, 01262a123ad9501d, 429db5b574a2ac08, 56b2d49da412cb28, 6a1717123fe4513c]
  tool: 1
---
# 已弃用的功能 {#deprecated-features}

2026-07-28 规范让五项内容退役。SDK 仍然实现了其中每一项，而且每一项现在都带有**弃用警告**。

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
    反过来用这个过滤器，就白得一个回归测试。在 pytest 配置的 `filterwarnings` 设置里加上 `"error::mcp.MCPDeprecationWarning"`，已弃用的调用就会**抛出异常**而不是发出警告。一个名为 `old_log`、仍在调用 `ctx.info()` 的工具不再通过，转而报告：

    ```text
    Error executing tool old_log: The logging capability is deprecated as of 2026-07-28 (SEP-2577).
    ```

    一行 pytest 配置，已弃用的调用就再也不可能悄悄溜回你的代码库而不让测试失败。

## 回顾 {#recap}

* 2026-07-28 规范弃用了**根目录**、服务器发起的**采样**和协议**日志**（都出自 [SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)），把**进度**限制为只能由服务器发往客户端，并移除了 **`ping`**。
* 替代做法那一列为你指明了去处：采样和根目录看 **[多轮往返请求](handlers/multi-round-trip.md)**，日志看 **[日志](handlers/logging.md)**，进度看 **[进度](handlers/progress.md)**。`ping` 什么都不需要。
* 弃用只是建议性的：线路上没有变化，在 2026 之前的会话上一切照常工作，你会看到一条醒目的 `MCPDeprecationWarning`（它是 `UserWarning`，所以默认开启）。
* 采样和根目录还需要一条反向通道（back-channel），而 2026-07-28 会话没有。在现代连接上，它们先警告，然后抛出异常。
* `warnings.filterwarnings("ignore", category=MCPDeprecationWarning)` 让整个类别静音；pytest 中的 `"error::mcp.MCPDeprecationWarning"` 把它变成测试失败。
* 新代码不应建立在其中任何一项之上。

本文档的其他每一页讲的都是当前的 API。
