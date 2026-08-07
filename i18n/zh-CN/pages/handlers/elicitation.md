# 征询 {#elicitation}

工具干到一半、缺一个答案，并不一定就得失败。

**征询（elicitation）**让它可以发问。在一次工具调用的中途，用户收到一个问题，而他们的答案会回到同一次函数调用里。

有两种模式：

* **表单模式**：你需要一个值（一次确认、一个日期、一个数量）。你描述字段，客户端渲染表单。
* **URL 模式**：你需要用户去别的地方（OAuth 同意页面、支付页面）。他们在那里做的任何事都不经过协议。

发问也有两种方式。首选是**解析器**：把问题挂在一个参数上，由 SDK 去问——在任何连接上都可以，不管客户端说的是哪个协议年代。直接的方式 `await ctx.elicit(...)` 是一个从**服务器**发往**客户端**的请求，而这个通道只有在客户端处于旧式连接（规范版本 2025-11-25 或更早）时才存在。本页两种都会讲；先从解析器开始。

## 用解析器发问 {#ask-with-a-resolver}

决定整个工具能否继续的问题——“确定吗？三个匹配的账户里选哪个？”——可以从工具体里提出来，放进一个**解析器**，由框架替你发问。

标注为 `Annotated[T, Resolve(fn)]` 的参数，会在执行工具体之前先运行 `fn` 来填充。解析器已经知道值时就直接返回值，否则返回 `Elicit(...)` 让框架去问：

```python title="server.py" hl_lines="24-30 35-36"
--8<-- "docs_src/elicitation/tutorial004.py"
```

* `confirm_delete` 按名字读取工具自己的 `path` 参数，列出文件夹内容，**只在必须时才征询**——空文件夹会解析为 `Confirm(ok=True)`，不需要与客户端往返。
* `delete_folder` 标注的是 `ElicitationResult[Confirm]`，于是框架注入完整的结果，工具用 `match` 处理每一种情况：接受并确认、接受但保留（`ok=False`）、拒绝、取消。
* `confirm` 参数永远不会出现在工具的输入模式里——`path` 由客户端提供，`confirm` 由解析器提供。

如果工具不需要分支处理，就改为标注未包装的模型（`Annotated[Confirm, Resolve(confirm_delete)]`）：接受时它拿到模型，拒绝或取消时调用以错误中止。

解析器在**每一种**连接上都能用。对于旧式连接上的客户端，SDK 直接把问题发给它；在 **2026-07-28** 连接上，SDK 把问题从调用中**返回**出来，客户端的下一次尝试带上答案。你的解析器完全察觉不到区别；底层发生的事情详见 **[多轮往返请求（multi-round-trip）](multi-round-trip.md)**。

发问只是解析器能做的事情之一。更通用的机制——不发问就能算出结果的依赖、依赖的依赖、模型能提供和不能提供什么——在 **[依赖](dependencies.md)** 页面。

## 在工具内部发问 {#ask-from-inside-the-tool}

工具也可以在自己的函数体中途停下来发问。

!!! warning
    `ctx.elicit()` 和 `ctx.elicit_url()` 是从**服务器**发往**客户端**的请求——这个通道只有在客户端处于旧式连接（规范版本 **2025-11-25**
    或更早）时才存在。在 **2026-07-28** 连接上不存在服务器发起的请求，所以
    这些调用会失败。解析器在两种情况下都能用。详见 **[协议版本](../protocol-versions.md)**。

`await ctx.elicit()` 接收一条消息和一个 Pydantic 模型：

```python title="server.py" hl_lines="9-11 20-23 25"
--8<-- "docs_src/elicitation/tutorial001.py"
```

* **`Context`** 参数就是 `ctx.elicit` 的来源；任何工具都可以接收一个。这个对象有自己的页面：**[Context](context.md)**。
* `AlternativeDate` 是你想要的答案的**模式**。
* 这个工具是 `async def`。它必须是：因为它会在中途停下来等一个人。
* 其他任何日期，工具都会立刻返回。只有必须问的时候它才问。
* 用户接受的日期会通过 `book_table` 自身回到流程里。答案和其他输入没有区别：如果备选日期也订满了，会再问一次，而不是盲目确认。

### 客户端收到什么 {#what-the-client-receives}

客户端收到你的消息，以及旁边一份由模型生成的 JSON Schema：

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

这份模式就是表单。`Field(description=...)` 是标签；默认值会预填输入框，并让该字段变为可选。这和 **[工具](../servers/tools.md)** 里描述的工具参数用的是同一套 Pydantic 转 JSON Schema 的机制。

!!! warning
    征询的模式没有工具输入模式那么有表现力。只支持扁平的原始类型字段：
    `str`、`int`、`float`、`bool`，或者字符串的 `Literal`（它会变成 `enum`）。
    在模型里再嵌一个模型，`ctx.elicit` 会在任何内容发送给客户端之前就抛出异常：

    ```text
    TypeError: Elicitation schema field 'address' rendered as {'$ref': '#/$defs/Address'}, which is not a valid PrimitiveSchemaDefinition
    ```

    你是在打断一个正在做事的人。如果答案需要嵌套，那它本来就应该是工具的参数。

### 三种答案 {#the-three-answers}

`result.action` 告诉你用户做了什么，而可能性正好只有三种：

* `"accept"`：用户提交了表单。`result.data` 是一个 `AlternativeDate` 实例，已经通过校验。
* `"decline"`：用户说了不。
* `"cancel"`：用户没有选择就关掉了这个问题。

`result.data` 只在 `"accept"` 时存在，所以示例里先检查 `result.action`。类型检查器会强制这个顺序：在 `result.action == "accept"` 之后，`result.data` 是 `AlternativeDate`；在这之前，根本没有 `.data`。

拒绝不是错误。工具自己决定拒绝意味着什么（这里是不预订），然后正常回复模型。

!!! tip
    答案在你的代码看到它之前，就已经按你的模型校验过了。客户端给一个 `bool` 字段发
    `"maybe"`，不会弄坏你的预订：调用会以模式不匹配的错误失败，你的 `if` 根本不会执行。

## 把用户引到一个 URL {#send-the-user-to-a-url}

有些东西绝不能经过模型或客户端：凭据、卡号、OAuth 授权同意。对这些，你要的不是数据，而是让用户去某个地方：

```python title="server.py" hl_lines="10-14 23"
--8<-- "docs_src/elicitation/tutorial002.py"
```

* `ctx.elicit_url()` 接收消息、要访问的 **URL**，以及一个由你指定的 `elicitation_id`：任意能在你的服务器内标识这次征询的字符串。
* 结果里只有一个 action，没有别的。`"accept"` 表示用户同意打开这个 URL，**不是**表示他们完成了另一端的事情。
* 支付发生在带外，在用户的浏览器和你的支付服务商之间。没有任何内容会通过 MCP 回来。

看看第二个工具。当你的服务器得知带外流程已经结束（通过 webhook、轮询；这里用第二个工具来模拟），`ctx.session.send_elicit_complete(...)` 会带上同一个 `elicitation_id` 发送 `notifications/elicitation/complete`。客户端就是靠这个知道可以不用再显示“正在等待支付……”了。没有它，客户端只能靠猜。

## 客户端这一侧 {#the-client-side}

服务器发问。客户端通过向 `Client(...)` 传入 **`elicitation_callback`** 来回答：

```python title="client.py" hl_lines="6-7 18"
--8<-- "docs_src/elicitation/tutorial003.py"
```

* 一个回调同时处理两种模式。`params` 是 `ElicitRequestFormParams` 和 `ElicitRequestURLParams` 的联合类型；用 `isinstance` 来分支。
* 对于 URL，把 `params.url` 展示给用户，然后返回他们选择的 action。绝不返回任何 `content`。
* 对于表单，真实的应用会渲染 `params.requested_schema`，并把用户的输入作为 `content` 返回。这里的实现总是用一个写死的答案说“是”，而这正是测试里想要的回调。
* 传入回调同时也是**能力声明**：服务器就是这样知道可以向这个客户端发问的。客户端还能为服务器回答哪些事情，见 **[客户端回调](../client/callbacks.md)**。

!!! info
    征询是从**服务器**发往**客户端**的请求，而这类请求只存在于经典握手的会话中，
    所以这个客户端传了 `mode="legacy"`。
    在 **2026-07-28** 连接上，工具改为通过调用的**返回值**来发问；
    那个流程见 **[多轮往返请求](multi-round-trip.md)**。

### 试一试 {#try-it}

用 Streamable HTTP 启动表单模式的 `ctx.elicit` 版 `server.py`（就是带 `book_table` 的那个，一行命令见 **[运行服务器](../run/index.md)**），然后运行客户端的 `main()`，向 `book_table` 预订圣诞节当天。

回调会打印它收到的问题：

```text
No tables for 2 on 2025-12-25. Would you like to try another date?
```

它回答 `{"accept_alternative": True, "date": "2025-12-27"}`，而一直卡在 `await ctx.elicit(...)` 里等待的工具完成了预订：

```text
Booked a table for 2 on 2025-12-27.
```

现在换成 URL 模式的 `server.py`，把同一个 `main()` 指向 `pay_deposit`：同一个回调走另一个分支，打印支付链接，工具返回“Complete the payment in your browser.”。一次往返，发生在调用中途，双向都走通了。

!!! check
    现在把 `Client` 里的 `elicitation_callback=` 去掉，再为圣诞节当天调用一次 `book_table`。
    整个调用会以协议错误失败：

    ```text
    Elicitation not supported
    ```

    没有注册回调的客户端从来没有声明 `elicitation` 能力，所以没有人可以问。你的工具拿到的
    不是 `"decline"`，而是一个异常。设计时要考虑这一点：每一次征询都需要对“如果问不了怎么办？”有一个合理的答案。

## 回顾 {#recap}

* 标注为 `Annotated[T, Resolve(fn)]` 的参数由解析器填充，解析器在必须发问时返回 `Elicit(...)`。它在每一种连接上都能用。
* 模式是一个扁平的 Pydantic 模型：只允许原始类型字段，返回时会校验。
* `result.action` 是 `"accept"`、`"decline"` 或 `"cancel"`；`result.data` 只在 accept 时存在。
* `await ctx.elicit(message, schema=Model)` 在工具体内部发问，`await ctx.elicit_url(message, url, elicitation_id)` 用于所有不能经过模型的东西（`ctx.session.send_elicit_complete(elicitation_id)` 表示带外的那部分已经完成）。两者都是服务器发往客户端的请求：需要客户端处于旧式连接上。
* 客户端用一个 `elicitation_callback` 来回答，按 params 类型分支；注册它就等于声明了这个能力。
* 在 2026-07-28 连接上，服务器不是推送问题，而是返回问题；同一个回调由 **[多轮往返请求](multi-round-trip.md)** 来驱动。

这个返回背后的一切（重试循环、保护 `requestState`、自己驱动它）都在 **[多轮往返请求](multi-round-trip.md)**。
