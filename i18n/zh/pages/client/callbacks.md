---
translation:
  sections: [adf3c545b5be46b6, 916cd3ab1c03f461, e9be7a8d0eb0a456, 565890a636288ecf, 6af7e49db9129ec3, 06b0238c174186af, 90c6043be435fcb0]
  tool: 1
---
# 客户端回调 {#client-callbacks}

MCP 里几乎所有请求都是单向的：从客户端发往服务器。

服务器也可以反过来向**客户端**要东西：向用户提一个问题、借用用户的模型做采样（sampling）、列出用户的工作区文件夹。要回答这些请求，把**回调**传给 `Client(...)` 即可。

## 一个会提问的服务器 {#a-server-that-asks}

下面这个服务器的工具没法独立完成任务：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/client_callbacks/tutorial001.py"
```

* `ctx.elicit(...)` 向**客户端**发送一个 `elicitation/create` 请求，然后等待。
* 在有人（填表单的人，或者你的代码）给出 `name` 之前，这个工具不会返回。

这是服务器那一半，归 **[征询](../handlers/elicitation.md)** 页面管。本页讲的是线路的另一端。

## 征询回调 {#the-elicitation-callback}

```python title="client.py" hl_lines="6-10 16-17"
--8<-- "docs_src/client_callbacks/tutorial002.py"
```

* 征询（elicitation）回调的签名是 `async (context, params) -> ElicitResult`。
* `params.message` 是问题本身。`params.requested_schema` 是服务器想要的答案的 JSON Schema。真正的客户端会据此渲染一个表单；这里的客户端直接自动填好。
* 返回 `ElicitResult(action="accept", content={...})`，或者 `action="decline"`，或者 `action="cancel"`。除此之外唯一的选择是 `ErrorData(...)`，它会拒绝这个请求，并让整个调用失败。
* `context` 是一个 `ClientRequestContext`：包含活动的 `session`、服务器的 `request_id`，以及它附带的 `meta`（如果有）。

!!! tip
    `params` 是两种征询模式的联合类型。这里 `params.mode` 是 `"form"`；`"url"` 请求携带的是 `params.url` 而不是模式（schema）。一个回调同时处理两种情况，按 `params.mode` 分支即可。完整写法见 **[征询](../handlers/elicitation.md)**。

### 试一试 {#try-it}

调用 `issue_card`，观察两端。

你的回调收到服务器的问题，已经解析好了：

```python
params.mode              # 'form'
params.message           # 'What name should go on the card?'
params.requested_schema  # {'properties': {'name': {'title': 'Name', 'type': 'string'}},
                         #  'required': ['name'], 'title': 'CardHolder', 'type': 'object'}
```

回调给出回答，`ctx.elicit(...)` 在工具内部恢复执行，工具随即完成：

```python
result.content  # [TextContent(type='text', text='Card issued to Ada Lovelace.')]
```

你发出一个 `tools/call`，服务器回过来一个 `elicitation/create`，由你的函数作答——全部发生在一次工具调用之内。

!!! info
    `Client(...)` 调用里的 `mode="legacy"` 是真正起作用的。默认情况下 `Client(...)` 协商的是现代协议路径，而那条路径没有供服务器向客户端发请求的反向通道（back-channel）：`ctx.elicit` 会在你的回调运行之前就失败。决定这一点的不是传输方式，而是协商出的协议，内存传输和 URL 传输都一样。只要你的客户端需要回答这类请求，就固定使用 `mode="legacy"`；本页背后的每个测试都是这么做的。详见 **[协议版本](../protocol-versions.md)**。

    在 2026-07-28 会话上，这个回调并没有失效，只是触发方式不同：当工具返回一个携带 `ElicitRequest` 的 `InputRequiredResult` 时，`Client` 会把该条目分派给同一个 `elicitation_callback`，并替你重试这次调用。那个流程见 **[多轮往返请求](../handlers/multi-round-trip.md)**。

## 回调就是能力 {#a-callback-is-a-capability}

你从没告诉服务器你的客户端能回答征询请求。是 SDK 说的。

客户端连接时会声明自己的 `capabilities`，和服务器的能力互为镜像。这个对象不用你写。**注册回调就是声明。**

| 你传入 | 客户端声明 |
| --- | --- |
| `elicitation_callback=` | `"elicitation": {"form": {}, "url": {}}` |
| `sampling_callback=` | `"sampling": {}` |
| `list_roots_callback=` | `"roots": {"listChanged": true}` |
| 一个都不传 | `{}` |

采样的子能力是唯一需要细化的地方：如果你的采样器能处理 `tools` / `tool_choice` 参数，就在传入 `sampling_callback` 的同时传入 `sampling_capabilities=SamplingCapability(tools=SamplingToolsCapability())`。服务器必须先看到 `sampling.tools` 已声明，才能发送这些参数。

`logging_callback` 和 `message_handler` 不在表里。它们处理的是通知，而通知不需要能力。

服务器用 `ctx.session.check_client_capability(...)` 读回这份声明。加一个这样的工具：

```python title="server.py" hl_lines="23-31"
--8<-- "docs_src/client_callbacks/tutorial003.py"
```

只带 `elicitation_callback` 连接并调用它：

```python
result.structured_content  # {'result': ['elicitation']}
```

三个回调都传，返回 `['elicitation', 'sampling', 'roots']`。一个都不传，返回 `[]`。

!!! check
    现在故意做错：**不带** `elicitation_callback` 连接，照样调用 `issue_card`。

    服务器的 `elicitation/create` 请求仍然会到达你的客户端，而 SDK 会替你作答——用一个错误，因为你从没说过自己能处理它。这个错误会拖垮整个调用。`call_tool` 不会返回一个 `is_error` 结果，而是直接抛出异常：

    ```text
    MCPError: Elicitation not supported
    ```

    这是协议错误（`-32600`，“invalid request”），不是工具错误：没有任何东西可供模型读取并重试。这正是 `client_features` 值得拥有的原因：行为规范的服务器会先检查再提问。

## 已弃用的那一对 {#the-deprecated-pair}

`sampling_callback` 回答 `sampling/createMessage`：服务器请求**你的**模型补全一些内容。`list_roots_callback` 回答 `roots/list`：服务器询问它可以在哪些目录（根目录（roots））里工作。

两者都能用，也都遵循上面的规则。但两者服务的 RPC 都被 **2026-07-28 规范移除了**：现代服务器不会在请求中途回调你的客户端，而是把请求作为工具结果的一部分交还给你（**[多轮往返请求](../handlers/multi-round-trip.md)**，即多轮往返（multi-round-trip））。回调本身并没有失效。当 `InputRequiredResult` 携带 `CreateMessageRequest` 或 `ListRootsRequest` 时，`Client` 的自动循环会把它分派给你在这里注册的同一个 `sampling_callback` 或 `list_roots_callback`。完整清单见 **[已弃用的功能](../deprecated.md)**。

要和还没迁移的服务器通信，仍然需要这些回调。签名如下：

```python title="client.py"
--8<-- "docs_src/client_callbacks/tutorial004.py"
```

* 采样回调收到完整的 `CreateMessageRequestParams`（`messages`、`model_preferences`、`max_tokens`），返回一个 `CreateMessageResult`。模型由**你**来运行，怎么运行都行；SDK 只负责传递请求。
* 根目录回调完全不接收参数，返回一个 `ListRootsResult`。
* 两者都可以改为返回 `ErrorData(...)` 来表示拒绝。

把它们传给 `Client(...)`，方式和 `elicitation_callback` 完全一样。

## 通知回调 {#the-notification-callbacks}

还有两个。它们都不声明任何东西。

`logging_callback` 接收服务器发送的 `notifications/message`，形式是 `LoggingMessageNotificationParams`（`level`、`logger`、`data`）。协议日志本身已被 2026-07-28 规范弃用（替代做法见 **[日志](../handlers/logging.md)**），所以这个回调是为仍在发出这类消息的服务器准备的。在 2026 年代的连接上，单有回调什么也收不到，因为 2026 服务器只向主动选择接收的请求发送日志消息：给 `Client(...)` 传入 `log_level="info"`（或其他级别），就会在每个请求上打上这个选择标记，并收到该级别及以上的消息。2026 之前的服务器会忽略它，保持原有的 `logging/setLevel` 行为。

`message_handler` 是兜底的：会话浮现出来的每一个服务器通知都会到达它（同时也到达各自专门的回调），在基于流的传输上，每一个传输层的 `Exception` 也是如此。有两种永远不会到达：`notifications/cancelled` 由 SDK 直接应用而不浮现出来；针对活动 `listen()` 流的订阅确认则由该流自己消费。给这个参数标注 `IncomingMessage` 类型（`ServerNotification | Exception`，从 `mcp.client` 导出）。唯一值得记住的写法是 `if isinstance(message, Exception): raise message`，这样断开的连接会大声报错，而不是悄悄消失。

## 回顾 {#recap}

* 服务器可以向客户端发送请求。用传给 `Client(...)` 的回调来回答它们。
* 征询回调是当前仍在使用的那个：`async (context, params) -> ElicitResult`，一个函数同时处理表单模式和 URL 模式。
* **注册回调就是声明能力。**没有它，SDK 会替你拒绝服务器的请求，整个调用以 `MCPError` 失败。
* 服务器用 `ctx.session.check_client_capability(...)` 在提问前先查明。
* `sampling_callback` 和 `list_roots_callback` 的工作方式相同，但服务的是已弃用的功能；现代服务器改用多轮往返请求。
* `logging_callback` 和 `message_handler` 接收通知。它们不声明任何东西。

`Client(...)` 的第一个参数是传输对象。**[客户端传输](transports.md)** 涵盖了每一种。
