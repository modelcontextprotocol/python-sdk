---
translation:
  sections: [b0389403e98d25ad, e2cf58b43b285e86, a363e1a38e1a5971, 6cfac078feb18013, b4535bd61df337e6, e97ed44207f929fd]
  tool: 1
---
# 依赖 {#dependencies}

工具的参数来自模型。但有些值绝不该由模型提供：从你的记录里查出来的价格、只有人才能给出的确认，以及任何模型一旦凭空编造就会出错的东西。

**依赖**是由你自己的函数填充的参数。给参数加上注解，指明函数，SDK 就会在工具运行之前调用它。

## 声明一个依赖 {#declare-one}

把参数类型包进 `Annotated[...]`，再加上 `Resolve(fn)`：

```python title="server.py" hl_lines="18-19 23"
--8<-- "docs_src/dependencies/tutorial001.py"
```

* `check_stock` 是一个**解析器**（resolver）：一个普通函数，SDK 在 `reserve_book` 之前运行它，它的返回值就成了 `stock` 参数。
* 它的 `title` 参数就是工具自己的 `title` 参数，**按名称**匹配。解析器看到的值和工具函数体看到的一模一样，都是校验过的值。
* 工具函数体一开始就拿到一个现成的 `Stock`。工具里没有查询代码，也没有“万一查不到怎么办”的铺垫。

!!! info
    如果用过 FastAPI，这就是 `Depends`。同样的做法，同样的理由：函数声明自己需要什么，框架负责提供，接线逻辑放在类型注解里。

### 对模型不可见 {#invisible-to-the-model}

这是 `tools/list` 为 `reserve_book` 报告的输入模式：

```json
{
  "type": "object",
  "properties": {
    "title": {"title": "Title", "type": "string"}
  },
  "required": ["title"],
  "title": "reserve_bookArguments"
}
```

只有一个属性。和 **[Context](context.md)** 里的 `Context` 一样，被解析的参数是你和 SDK 之间的约定：`stock` 不在模式里，模型从不会知道它的存在，客户端即便硬塞一个 `stock` 值过来也会被忽略。工具能收到的只有解析器给出的值。

最后这一点才是关键。模型无法提供的参数，就是模型无法弄错的参数。

### 试一试 {#try-it}

用 MCP Inspector 运行服务器：

```console
uv run mcp dev server.py
```

`reserve_book` 的表单只有一个 `title` 字段，哪儿都找不到 `stock`。用 `Dune` 调用它：

```text
Reserved 'Dune' (6 copies left).
```

工具函数体什么都没查：`check_stock` 先运行，它返回的 `Stock` 作为参数传了进来。换成 `Neuromancer` 试试，同一个解析器会给工具一个零。

!!! tip
    你当然可以直接在工具函数体里调用 `check_stock(title)`。如果这个值不只是一次辅助函数调用那么简单，就把它声明为依赖：每个需要库存的工具都声明同一个参数，而不管有多少个工具声明它，SDK 每次调用最多只运行一次解析器。后面几节补上其余内容：相互依赖的解析器，以及会去问用户的解析器。

## 依赖的依赖 {#dependencies-of-dependencies}

解析器可以用同样的注解声明自己的依赖：

```python title="server.py" hl_lines="22 29-30"
--8<-- "docs_src/dependencies/tutorial002.py"
```

* `estimate_delivery` 依赖 `check_stock`。SDK 按顺序运行这张图：先查库存，再算预估，最后才是工具。
* `stock` 和 `delivery` 最终都需要 `check_stock`，但它**每次调用只运行一次**。一次库存查询，两个使用者。
* 不需要注册任何东西。注解**本身就是**这张图。

!!! check
    别轻信“每次调用一次”这句话。在 `check_stock` 里放一个 `print`，然后从 Inspector 调用 `order_book`：每次调用打印一行。两个使用者，一次查询。

SDK 在工具注册时分析这张图，而不是在调用时。遇到它无法归类的参数——既不是 `Context`，也不是 `Resolve(...)`，也不是某个工具参数的名字——或者解析器之间出现环，都会在启动时抛出 `InvalidSignature`。服务器在任何客户端连上来之前就会失败，错误里会点名出问题的参数或解析器。

解析器的参数和工具的参数按完全相同的方式解析：另一个 `Resolve(...)`、按名称匹配的工具自身参数，或者 `Context`——`ctx.headers`、生命周期对象，全都可以。

!!! warning
    在 HTTP 传输上，`Context` 包含 `ctx.headers`。请求头是**客户端提供的输入**，和任何工具参数一样：用来传区域设置或功能开关没问题，但绝不能当作身份。调用者是谁由你的授权层决定（**[授权](../run/authorization.md)**），而不是一个谁都能设置的请求头。

!!! tip
    “每次调用一次”就是字面意思：下一次 `tools/call` 会再次运行 `check_stock`。需要比单次请求活得更久的资源——数据库连接池、HTTP 客户端——应该放在**[生命周期](lifespan.md)**里，解析器可以通过 `ctx.request_context.lifespan_context` 拿到它。

## 必要时才问 {#ask-when-you-must}

解析器不一定要知道答案。它可以返回 `Elicit(message, Model)`，SDK 会去问用户——也就是**[征询](elicitation.md)**（elicitation）机制，由 SDK 替你运行：

```python title="server.py" hl_lines="26-32 39"
--8<-- "docs_src/dependencies/tutorial003.py"
```

* 有货：`confirm_backorder` 直接返回一个 `Backorder`。**不提问，不往返。**只有当用户的回答真正有用时才会打扰他们。
* 缺货：SDK 发出征询，按 `Backorder` 校验回答，然后注入。解析器完全不碰协议。
* 工具像读取其他参数一样读取 `backorder.confirm`。回答**否**也算回答：征询以 `confirm=False` 被接受，工具照常运行，但不会下单。提问变成了前置条件，而不是塞在工具函数体里的管道代码。

那如果用户干脆不回答——拒绝这个问题，或者取消它呢？

!!! check
    对 `Neuromancer` 运行 `order_book` 并拒绝回答。注解写成 `Annotated[Backorder, Resolve(...)]` 时，工具函数体根本不会运行；调用失败并返回一个模型能读懂的错误结果：

    ```text
    Error executing tool order_book: Resolver for parameter 'backorder' could not resolve: elicitation was decline
    ```

对前置条件来说这是正确的默认行为：没有回答，就没有订单。如果拒绝是工具想要自行处理的一种结果——跳过缺货预订，但仍然推荐另一本书——就改为注解 `ElicitationResult[Backorder]`，工具会收到完整的接受/拒绝/取消结果并据此分支。**[征询](elicitation.md)**展示了这种写法，以及关于提问的其他一切：模式规则、三种回答、客户端一侧的对话。

!!! info
    框架根据协商出的协议版本选择问题走哪种传输方式；上面的代码在两种情况下完全相同。在 **2026-07-28** 及之后，问题搭载在一次多轮往返（multi-round-trip）的 `tools/call` 里——服务器返回问题，客户端的 `elicitation_callback` 回答它，`Client` 替你重试调用（**[多轮往返请求](multi-round-trip.md)**）。在 **2025-11-25** 及之前，它是调用中途的一次同步征询请求。每个问题在每次调用中恰好被问一次——这是对问题的保证，而不是对解析器的保证。在多轮往返形式下，每当调用在一个问题之后恢复，任何解析器都可能再次运行，所以 `return Elicit(...)` 之前的代码在每一轮都会执行；随后记录下的回答会满足重复出现的问题，而不会再次打扰用户。只有当解析器提问时才会去查记录下的回答；像 `check_stock` 这样**不**提问就给出答案的解析器，永远提供它自己算出来的值。因为每个回答都要匹配回它的问题，会发起征询的解析器必须根据工具的参数和先前的回答确定性地推导出问题。每次调用生成的值（`default_factory` 生成的 id、时间戳）在每一轮都会重新推导，绝不能出现在需要绑定回答的问题里。用这种易变数据构造的问题会让每个记录下的回答看起来都已过期，于是服务器每一轮都会重新提问，直到客户端的轮数上限终止这次调用。

## 问客户端，而不是用户 {#ask-the-client-not-the-user}

征询是解析器能问的三种问题之一，多轮往返流程不允许其他问题。另外两种问的是**客户端**而不是用户：返回 `Sample(...)` 通过客户端发起一次 LLM 调用（一个 `sampling/createMessage` 请求），或者返回 `ListRoots()` 获取客户端当前的根目录（roots）。这两者都没有接受/拒绝的结果；使用者直接注解结果类型，`CreateMessageResult`（请求带有 `tools` 或 `tool_choice` 时为 `CreateMessageResultWithTools`）或 `ListRootsResult`：

```python title="server.py" hl_lines="10-15 21"
--8<-- "docs_src/dependencies/tutorial004.py"
```

* 框架对它们的路由方式和 `Elicit` 完全一样：在 **2026-07-28** 上走多轮往返的 `tools/call`，在 **2025-11-25** 上走独立的服务器->客户端请求。未声明的能力会以 `-32021` 协议错误拒绝调用（`sampling`、`roots`、表单模式的 `elicitation`；请求带有 `tools` 或 `tool_choice` 时为 `sampling.tools`）。
* 上面 info 框里关于问题的所有内容原样适用：`Sample` 请求按其精确的渲染结果匹配到记录下的结果，所以要根据工具的参数和先前的回答确定性地构造它；这样客户端为 LLM 调用付出的代价是每次工具调用一次，而不是每轮一次。记录下的结果在本次调用剩余时间里都搭载在 `request_state` 上，所以一个非常大的补全会让后面每次往返都更重。
* 独立的采样（sampling）和根目录**功能**在 2026-07-28 已弃用（SEP-2577）。需要客户端模型的新服务器应通过这个载体提问；不需要的服务器应直接对接 LLM 提供商。`include_context` 取 `"none"` 以外的值本身也已弃用，不要用。

## 回顾 {#recap}

* 在工具参数上写 `Annotated[T, Resolve(fn)]`：SDK 运行 `fn` 并注入它的返回值。
* 被解析的参数对模型不可见，客户端也无法提供。模型绝不能编造的值——价格、身份、权限——就该放在这里。
* 解析器的参数按同样的方式解析：`Context`、另一个 `Resolve(...)`，或按名称匹配的工具参数。不管有多少使用者，这张图每一轮最多运行每个解析器一次；每个问题恰好问一次，而调用在一个问题之后恢复时，任何解析器都可能再次运行。
* 有问题的图在注册时就以 `InvalidSignature` 失败，而不是在调用中途。
* 返回 `Elicit(message, Model)` 去问用户，只在必要时才问。未包装的注解在拒绝时中止；`ElicitationResult[T]` 让工具自行分支。
* 返回 `Sample(...)` 或 `ListRoots()` 向客户端要一次 LLM 补全或根目录列表；注入的是原始结果。

服务器在启动时一次性构建的状态，以及处理函数如何拿到它，见 **[生命周期](lifespan.md)** 页面。
