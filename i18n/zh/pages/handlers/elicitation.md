---
translation:
  sections: [335ca2a0b266f003, d1ad562d3fe87bc0, 0bb1396c86daeba4, d1cb1235bb9ee267, 833179c09d239c83, e5d6dec2d2e655e8]
  tool: 1
---
# 征询 {#elicitation}

一个工具活干到一半、只差一个答案，不必因此失败。

**征询**（elicitation）让它可以开口问。在一次工具调用的中途，用户会收到一个问题，他们的回答会回到同一次函数调用里。

有两种模式：

* **表单模式**：你需要一个值（一次确认、一个日期、一个数量）。你描述字段，客户端渲染表单。
* **URL 模式**：你需要用户去别的地方（OAuth 授权页面、支付页面）。他们在那里做的任何事都不经过协议。

提问的方式也有两种。首选的是**解析器**：把问题挂在一个参数上，SDK 负责去问——在任何连接上都行，不管客户端说的是哪个时代的协议。直接的方式是 `await ctx.elicit(...)`，它是一个从**服务器**发往**客户端**的请求，而这条通道只对处于旧版连接（规范版本 2025-11-25 或更早）的客户端存在。本页两种都讲，先从解析器开始。

## 用解析器提问 {#ask-with-a-resolver}

一个把关整个工具的问题——“确定吗？三个匹配的账户里选哪个？”——可以从工具函数体里提出来放进**解析器**，由框架替你去问。

标注为 `Annotated[T, Resolve(fn)]` 的参数，会在工具函数体执行之前通过运行 `fn` 来填充。解析器已经知道值时直接返回它；否则返回 `Elicit(...)`，让框架去问：

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` 按名字读取工具自己的 `path` 参数，列出文件夹内容，并且**只在必须时才征询**——空文件夹直接解析为 `Confirm(ok=True)`，不需要和客户端往返。
* `delete_folder` 标注的是 `ElicitationResult[Confirm]`，所以框架注入完整的结果，工具用 `match` 处理每一种情况：接受并确认、接受但保留（`ok=False`）、拒绝、取消。
* `confirm` 参数永远不会出现在工具的输入模式里——客户端提供 `path`，解析器提供 `confirm`。

如果工具不需要分支，就改为标注解包后的模型（`Annotated[Confirm, Resolve(confirm_delete)]`）：接受时它收到模型，拒绝或取消时调用以错误中止。

解析器在**每一种**连接上都能工作。对旧版连接上的客户端，SDK 直接把问题发给它；在 **2026-07-28** 连接上，SDK 把问题从这次调用里**返回**出去，客户端的下一次尝试会带上答案。你的解析器感觉不到区别；底层发生的事情是 **[多轮往返请求](multi-round-trip.md)**（multi-round-trip）。

提问只是解析器能做的事情之一。通用机制——不提问直接算出值的依赖、依赖的依赖、模型能提供什么不能提供什么——见 **[依赖](dependencies.md)** 页面。

## 在工具内部提问 {#ask-from-inside-the-tool}

工具也可以在自己的函数体中途停下来提问。

!!! warning
    `ctx.elicit()` 和 `ctx.elicit_url()` 是从**服务器**发往**客户端**的请求——这条通道只对处于旧版连接（规范版本 **2025-11-25** 或更早）的客户端存在。在 **2026-07-28** 连接上没有服务器发起的请求，所以这些调用会失败。解析器在两者上都能用。详见 **[协议版本](../protocol-versions.md)**。

`await ctx.elicit()` 接受一条消息和一个 Pydantic 模型：

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** 参数就是提供 `ctx.elicit` 的东西；任何工具都可以接收一个。这个对象有自己的页面：**[Context](context.md)**。
* `AlternativeDate` 是你想要的答案的**模式**。
* 工具是 `async def`。必须是：它会在中途停下来等一个人。
* 其他任何日期，工具直接返回。只在必须时才问。
* 用户接受的日期会重新走一遍 `book_table` 本身。答案和其他输入一样是输入：如果替代日期也订满了，会再问一次，而不是盲目确认。

### 客户端收到什么 {#what-the-client-receives}

客户端拿到你的消息，旁边还有一个由模型生成的 JSON Schema：

```json
{
  "properties": {
    "accept_alternative": {
      "description": "Try another date?",
      "title": "Accept Alternative",
      "type": "boolean"
    },
    "date": {
      "default": "2025-12-26",
      "description": "Alternative date (YYYY-MM-DD)",
      "title": "Date",
      "type": "string"
    }
  },
  "required": ["accept_alternative"],
  "title": "AlternativeDate",
  "type": "object"
}
```

这个模式就是表单。`Field(description=...)` 是标签；默认值会预填输入框，并让该字段变成可选。这和 **[工具](../servers/tools.md)** 里描述的工具参数用的是同一套 Pydantic 转 JSON Schema 的机制。

!!! warning
    征询的模式不如工具的输入模式表达力强。只能是扁平的原始类型字段：`str`、`int`、`float`、`bool`，或字符串的 `Literal`（会变成 `enum`）。在模型里再放一个模型，`ctx.elicit` 会在任何东西发给客户端之前抛出异常：

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    你是在打断一个正在做事的人。如果答案需要嵌套，它本该是工具的参数。

### 三种答案 {#the-three-answers}

`result.action` 告诉你用户做了什么，恰好只有三种可能：

* `"accept"`：他们提交了表单。`result.data` 是一个 `AlternativeDate` 实例，已经验证过。
* `"decline"`：他们说了不。
* `"cancel"`：他们没做选择就关掉了问题。

`result.data` 只在 `"accept"` 时存在，这就是示例先检查 `result.action` 的原因。类型检查器会强制这个顺序：在 `result.action == "accept"` 之后，`result.data` 是 `AlternativeDate`；在那之前根本没有 `.data`。

拒绝不是错误。由工具决定拒绝意味着什么（这里是不订位），然后正常回答模型。

!!! tip
    答案在你的代码看到之前就已按你的模型验证过。一个给 `bool` 字段发来 `"maybe"` 的客户端不会弄坏你的订位：调用以模式不匹配的错误失败，你的 `if` 根本不会执行。

## 把用户引到一个 URL {#send-the-user-to-a-url}

有些东西绝不能经过模型或客户端：凭据、卡号、OAuth 授权。对这些，你不索要数据，而是请用户去一个地方：

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` 接受消息、要访问的 **URL**，以及一个你自己选的 `elicitation_id`：任何能在你的服务器内标识这次征询的字符串。
* 结果只有一个 action，别无其他。`"accept"` 表示用户同意打开这个 URL，**不是**表示他们完成了另一头的事情。
* 支付在带外进行，发生在用户的浏览器和你的支付提供商之间。没有任何内容会通过 MCP 回来。

看第二个工具。当你的服务器得知带外流程结束了（一个 webhook、一次轮询；这里建模成第二个工具），`ctx.session.send_elicit_complete(...)` 会用同一个 `elicitation_id` 发送 `notifications/elicitation/complete`。客户端就是这样知道可以不再显示“waiting for payment...”的。没有它，客户端只能猜。

## 客户端一侧 {#the-client-side}

服务器提问。客户端通过给 `Client(...)` 传一个 **`elicitation_callback`** 来回答：

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 一个回调处理两种模式。`params` 是 `ElicitRequestFormParams` 和 `ElicitRequestURLParams` 的联合类型；用 `isinstance` 分支。
* 对 URL，把 `params.url` 展示给用户，返回他们选的 action。永远不带任何 `content`。
* 对表单，真实的应用会渲染 `params.requested_schema`，把用户的输入作为 `content` 返回。这个回调总是用一个固定答案说“是”，这正是测试里想要的回调。
* 传入回调同时也是**能力声明**：服务器就是这样得知这个客户端可以被提问。客户端能替服务器回答的其他东西在 **[客户端回调](../client/callbacks.md)**。

!!! info
    征询是从**服务器**发往**客户端**的请求，而这类请求只存在于经典握手的会话上，这就是这个客户端传 `mode="legacy"` 的原因。在 **2026-07-28** 连接上，工具改为把问题从调用里**返回**出去来提问；那个流程见 **[多轮往返请求](multi-round-trip.md)**。

### 试一试 {#try-it}

用 Streamable HTTP 启动 `ctx.elicit` 表单模式的 `server.py`（`book_table` 那个）（那条一行命令见 **[运行服务器](../run/index.md)**），然后运行客户端的 `main()`，向 `book_table` 要圣诞节当天的位子。

回调会打印它收到的问题：

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

它回答 `{"accept_alternative": True, "date": "2025-12-27"}`，而一直在 `await ctx.elicit(...)` 里等着的工具完成订位：

```text
Booked a table for 2 on 2025-12-27.
```

现在换成 URL 模式的 `server.py`，让同一个 `main()` 去调 `pay_deposit`：同一个回调走另一条分支，打印支付链接，工具返回“Complete the payment in your browser.”。一次往返，调用中途，双向都有。

!!! check
    现在从 `Client` 里去掉 `elicitation_callback=`，再为圣诞节当天调一次 `book_table`。整个调用以协议错误失败：

    ```text
    Elicitation not supported
    ```

    没注册回调的客户端从未声明 `elicitation` 能力，所以没人可问。你的工具收到的不是 `"decline"`，而是一个异常。要为此设计：每一次征询都需要对“要是问不了怎么办？”有一个合理的答案。

## 回顾 {#recap}

* 标注为 `Annotated[T, Resolve(fn)]` 的参数由解析器填充，解析器需要提问时返回 `Elicit(...)`。它在每种连接上都能用。
* 模式是一个扁平的 Pydantic 模型：只能有原始类型字段，回来时会验证。
* `result.action` 是 `"accept"`、`"decline"` 或 `"cancel"`；`result.data` 只在 accept 时存在。
* `await ctx.elicit(message, schema=Model)` 在工具函数体内部提问，`await ctx.elicit_url(message, url, elicitation_id)` 用于一切绝不能经过模型的东西（`ctx.session.send_elicit_complete(elicitation_id)` 表示带外部分已完成）。两者都是服务器到客户端的请求：需要客户端处于旧版连接。
* 客户端用一个 `elicitation_callback` 回答，按 params 类型分支；注册它就是声明能力。
* 在 2026-07-28 连接上，服务器返回问题而不是推送问题；同一个回调的输入来自 **[多轮往返请求](multi-round-trip.md)**。

那次返回之下的一切（重试循环、保护 `requestState`、自己驱动它）见 **[多轮往返请求](multi-round-trip.md)**。
