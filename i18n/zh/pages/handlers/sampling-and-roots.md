---
translation:
  sections: [5c82b20cbd65ded0, 9dc22632be79a533, 1fb8f452e990c456, 42666ab914ff0cb1, c4e0cb3667fd5ff9]
  tool: 1
---
# 采样与根目录 {#sampling-and-roots}

处理函数还可以向已连接的客户端索取两样东西：一是用客户端自己的模型生成一次补全，即**采样**（sampling）；二是客户端的工作区文件夹，即**根目录**（roots）。

两者在 SDK 支持的每个协议版本上都仍然可用。但在围绕它们做设计之前，先读下面的警告：

!!! warning "已被 2026-07-28 规范弃用"
    采样和根目录自 `2026-07-28` 起已弃用（[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/2577)）。它们仍然完全可用，并且会在规范中至少保留十二个月才有可能被移除，但新的实现不应再建立在它们之上。建议的迁移方式：直接对接 LLM 提供商的 API，而不是使用采样；通过工具参数、资源 URI 或服务器配置传递目录，而不是使用根目录。SDK 范围内的完整清单见 **[已弃用的功能](../deprecated.md)**。

## 采样：借用客户端的模型 {#sampling-borrow-the-clients-model}

解析器返回 `Sample(...)`，工具就会收到补全结果，走的是和 **[依赖](dependencies.md)** 中运行 `Elicit` 相同的依赖机制：

```python title="server.py" hl_lines="10-15 19"
--8<-- "docs_src/sampling_and_roots/tutorial001.py"
```

* `Sample(messages, max_tokens=...)` 与 `sampling/createMessage` 的参数一一对应。注入的值是客户端的 `CreateMessageResult`；如果传入 `tools` 或 `tool_choice`，注入的就是 `CreateMessageResultWithTools`。
* 客户端必须声明了 `sampling` 能力（如果传入 `tools` 或 `tool_choice`，则需要 `sampling.tools`）。如果没有声明，调用会以 `-32021` 协议错误失败，而不会发出一个客户端无法处理的请求。没有反向通道（back-channel）的 2026 年之前的会话，会照常以无反向通道的错误失败，因为根本没有可以发送的通道。
* 在 `2026-07-28` 上，请求在多轮往返（multi-round-trip）流程中送达（见 **[多轮往返请求](multi-round-trip.md)**）；在 `2025-11-25` 上，它是发给客户端的一个独立请求。两种情况下代码都一样，但要注意多轮往返的规则：请求在各轮重试中必须渲染得完全一致，所以只能用工具的参数和其他稳定数据来构造它。
* 不要动 `include_context`：`"none"` 以外的值本身也已弃用（SEP-2596），而且需要一个几乎没有客户端会声明的能力。

## 根目录：这个该放哪儿？ {#roots-where-should-this-go}

根目录是客户端声明服务器可以操作的文件夹。它们只是参考信息，不是访问控制机制。解析器返回 `ListRoots()`：

```python title="server.py" hl_lines="10-11 15"
--8<-- "docs_src/sampling_and_roots/tutorial002.py"
```

* 注入的 `ListRootsResult` 带有一个 `Root` 列表：每项是一个 `file://` URI 和一个可选的显示名称。
* 门槛和采样一样：没有声明 `roots` 能力时，调用会以 `-32021` 失败，而不会发出请求。

在线路的另一端，客户端用它已有的回调来响应这两种请求：`sampling_callback` 和 `list_roots_callback`，详见 **[客户端回调](../client/callbacks.md)**。

## 在 2025 年代的连接上 {#on-2025-era-connections}

`ctx.session.create_message(...)` 和 `ctx.session.list_roots()` 仍然存在，供直接驱动会话的代码使用。它们只在存在反向通道的地方有效（2025 年代、非无状态的连接），并且调用它们会触发弃用警告。上面的解析器标记才是受支持的形式：它们根据协商出的版本选择投递方式，也不会发出警告。

## 回顾 {#recap}

* 从解析器返回 `Sample(...)` 或 `ListRoots()`；工具会像接收其他任何依赖项一样收到 `CreateMessageResult` 或 `ListRootsResult`。
* 客户端必须声明对应的能力，否则调用会以 `-32021` 失败，而不会发出请求。
* 两个功能在 `2026-07-28` 上都已弃用：目前完全可用，但不适合新的设计。优先使用提供商 API 而非采样，优先使用显式参数而非根目录。

报告一个耗时工具的进度：**[进度](progress.md)**。
