---
translation:
  sections: [05891e7cc1938a13, b3c01a6af28c51ee, 7ffc91f5e38bdfe0, 717d3f235a8333a7, f471a13b2fe5d737, ed6af2df4b656dff]
  tool: 1
---
# 扩展 {#extensions}

**扩展**是一组归在同一个标识符之下、需要主动启用的 MCP 行为。

在服务器上，它可以贡献工具、资源和新的请求方法，还可以包裹 `tools/call`。在客户端上，它可以认领额外的 `tools/call` 结果形态，并观察厂商通知。两端各自在自己的 `capabilities.extensions` 下声明，对没有要求它的人来说一切照旧。这就是约定（[SEP-2133](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2133)），它只有一条铁律：**扩展默认关闭**。

## 使用扩展 {#using-an-extension}

在构造时传入实例：

```python title="server.py"
--8<-- "docs_src/extensions/tutorial001.py"
```

完成。服务器现在会在 `capabilities.extensions` 下声明 `io.modelcontextprotocol/ui`，并提供该扩展贡献的一切。

`Apps` 是内置的参考扩展，它有自己的页面：**[MCP Apps](apps.md)**。

!!! note
    扩展在构造时就固定下来。没有可以事后调用的 `add_extension`：客户端连着的时候，服务器的能力映射不应该变。

能力映射随 `server/discover` 传递，这是 **2026-07-28** 的路径。旧版 `initialize` 握手没有地方放它，所以旧版客户端根本看不到这个扩展。设计时要考虑到这一点：扩展是对服务器的**增强**，绝不能成为服务器唯一可用的途径。

## 编写自己的扩展 {#writing-your-own}

继承 `Extension`，只重写需要的部分。每个方法都有默认实现。

### 标识符 {#the-identifier}

```python
--8<-- "docs_src/extensions/tutorial002.py"
```

标识符是一个 `vendor-prefix/name` 字符串，遵循规范中 `_meta` 键的语法：用点分隔的标签（每个以字母开头，以字母或数字结尾），一个斜杠，然后是名称。它在**类定义时**就会被校验，所以拼写错误不会等到服务器启动才暴露：

```text
TypeError: Stamps.identifier must be a `vendor-prefix/name` string
(reverse-DNS prefix required), got 'stamps'
```

用你控制的域名作前缀。`io.modelcontextprotocol/*` 留给 MCP 项目自己规范的扩展。

### 贡献工具 {#contributing-tools}

最小的有用扩展就是一个工具加一份设置映射：

```python title="server.py" hl_lines="17 19-20 22-23 26"
--8<-- "docs_src/extensions/tutorial003.py"
```

* `tools()` 返回 `ToolBinding`。服务器注册每一个的方式与你自己调用 `mcp.add_tool(...)` 完全一样：同样的模式生成，同样的 `Context` 注入，一切都一样。
* `settings()` 是在 `capabilities.extensions["com.example/stamps"]` 处声明的值。返回 `{}`（默认值）表示声明该扩展但不带任何设置。
* 扩展永远拿不到服务器。它以数据的形式声明贡献，由 `MCPServer` 消费。没有可供修改的 `self.server`。

`main()` 就是证明：一个直接对着 `mcp` 的内存客户端：

```python title="server.py" hl_lines="29-34"
--8<-- "docs_src/extensions/tutorial003.py"
```

### 提供自己的方法 {#serving-your-own-methods}

扩展可以注册**新的请求方法**：它自己的动词，与规范定义的方法并列提供：

```python title="server.py" hl_lines="16-22 31 40-48"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `SearchParams` 继承 `RequestParams`，因此 2026 的 `_meta` 信封能统一解析，处理函数拿到的是校验过的参数，而不是原始 dict。对客户端能控制的东西加上限制：`Field(ge=1, le=100)` 会在你的代码为它分配任何东西之前就拒绝离谱的 `limit`。
* `require_client_extension(ctx, EXTENSION_ID)` 是门槛：没有声明该扩展的客户端会收到 `-32021`（缺少必需的客户端能力）错误，并附带规范要求的机器可读 `requiredCapabilities` 载荷。
* `protocol_versions=frozenset({"2026-07-28"})` 把该方法固定在一个线路版本上。在其他任何版本下，客户端得到 `METHOD_NOT_FOUND`，就跟这个方法在那里不存在一样。对那个客户端而言，它确实不存在。

方法是**严格增量**的。SDK 在构造时而不是运行时强制这一点：

* 为规范定义的方法（`tools/list`、`completion/complete`……）创建 `MethodBinding`，会在构造该绑定时抛出 `ValueError`。核心动词属于服务器。
* 两个扩展绑定同一个方法，第二个注册时抛出异常。“后写者胜”正是插件互相破坏的方式，我们不这么做。
* 空的 `protocol_versions` 集合同样抛出异常：一个永远无法提供的方法是 bug，不是配置。

### 客户端一侧 {#the-client-side}

同一个文件的 `main()` 就是客户端的全部内容，两半都在：

```python title="server.py" hl_lines="54-58"
--8<-- "docs_src/extensions/tutorial004.py"
```

* `Client(..., extensions=[advertise(EXTENSION_ID)])` 声明该扩展。这些声明会变成 `ClientCapabilities.extensions`：在 2026-07-28 连接上，该映射随每个请求的 `_meta` 信封传递，所以服务器在**每个**请求上都能看到它；在旧版连接上，它随 `initialize` 握手传递。服务器代码不用关心是哪一种：`require_client_extension(ctx, ...)` 和 `ctx.session.check_client_capability(...)` 在两条路径上都会读取正确的来源。
* 厂商方法要往下一层，用 `client.session.send_request(...)`；`Client` 只为规范动词提供一等方法。`send_request` 接受任何 `Request` 子类，所以厂商请求原样传入即可。

### 拦截 `tools/call` {#intercepting-toolscall}

唯一的拦截型钩子。重写 `intercept_tool_call` 来观察、短路或否决一次工具调用：

```python title="server.py" hl_lines="17-24"
--8<-- "docs_src/extensions/tutorial005.py"
```

* `params` 是校验过的 `CallToolRequestParams`：不用碰原始 JSON 就能拿到 `params.name` 和 `params.arguments`。决定运行哪个工具调用的也是它：通过 `call_next` 传入一个改写过的 context，改变的是处理函数在 `ctx` 上看到的内容，而不是工具调用本身。线路层面的请求改写属于[中间件](middleware.md)的事。
* `call_next(ctx)` 运行链上剩余的部分并返回处理函数的结果。原样返回它（观察）、返回别的东西（替换），或者抛出 `MCPError`（拒绝）。无论返回什么，都会像任何处理函数结果一样被序列化，包括 2026 时代的 `serverInfo` 身份标记，所以短路的拦截器永远不会产生匿名或不符合模式的响应。
* 有多个扩展时，拦截器按注册顺序嵌套：`extensions=[...]` 里的第一个扩展在最外层。
* 默认实现是直通。如果服务器的扩展都没有重写这个钩子，裸 `tools/call` 处理函数就保持原封不动。不用的东西不用付出代价。

这个钩子只包裹 `tools/call`，别无其他。涉及每条消息的事情，用[中间件](middleware.md)。它就是干这个的。

## 使用客户端扩展 {#using-a-client-extension}

**客户端扩展**是从消费一侧看的同一份约定：一组归在同一个标识符之下的客户端行为。把实例传给 `Client(extensions=[...])`，然后照常调用工具：

```python title="client.py" hl_lines="66-68"
--8<-- "docs_src/extensions/tutorial006.py"
```

`call_tool("buy", ...)` 返回一个普通的 `CallToolResult`，和其他任何调用一样。扩展改变的是：服务器现在可以用 `receipt` **结果形态**而不是最终结果来回答 `buy`，`Receipts` 会在 `call_tool` 返回之前把它完成（这里是用一次后续调用兑换收据）。调用处什么都不用动。

去掉这个扩展，这一切就都不存在：服务器的门槛会拒绝没有声明它的客户端（错误 -32021），而跳过门槛的服务器发来的被认领形态会校验失败，正如规范对无法识别的 `resultType` 所要求的那样。默认关闭，线路两端都是。

要声明一个**没有**任何客户端行为的标识符（服务器按该能力设门槛，客户端什么都不做，就像上面的 search 客户端那样），用 `advertise()`：

```python
from mcp.client import advertise

client = Client(mcp, extensions=[advertise("com.example/search")])
```

## 编写客户端扩展 {#writing-a-client-extension}

继承 `ClientExtension`，只重写需要的部分。贡献分三类，各有默认实现：`settings()`、`claims()` 和 `notifications()`。

```python title="client.py" hl_lines="17-18 43-44 46-47"
--8<-- "docs_src/extensions/tutorial006.py"
```

* 标识符遵循与服务器端相同的语法，在类定义时校验。
* `claims()` 返回 `ResultClaim`：一个线路标签、解析它的模型，以及完成它的解析器。模型必须用 `result_type: Literal["receipt"]` 固定该标签，且不得继承该动词的核心结果类型；两者都在构造认领时强制检查。像 `receipt_token` 这样的厂商字段在线路上原样传输：被替换的形态会逐字到达客户端。
* 解析器接收解析后的模型和一个 `ClaimContext`；`ctx.session` 与 `client.session` 是同一个公开句柄，所以后续操作就是普通的会话调用。它返回该动词正常的 `CallToolResult`。
* `settings()` 是在 `ClientCapabilities.extensions[identifier]` 处声明的值，在构造 `Client` 时读取一次。

`notifications()` 声明要观察的厂商服务器通知：

```python
def notifications(self) -> Sequence[NotificationBinding[Any]]:
    return [NotificationBinding(method="notifications/receipts", params_type=ReceiptEvent, handler=self.on_receipt)]
```

处理函数按分发顺序逐个接收校验过的参数。它只观察，不能否决，也不能回复。

两条不起眼的规则。认领只在 2026-07-28 连接上生效，能力声明随之变化：在旧版连接上，认领会消失，标识符也随之从声明中去掉，所以客户端永远不会声明一个其形态自己会拒绝的扩展。另外，如果想自己拿到被认领的形态而不交给解析器，调用 `client.session.call_tool(..., allow_claimed=True)`；没有这个标志时，被认领的形态到达会话层调用方会抛出 `UnexpectedClaimedResult`。

### 扩展动词 {#extension-verbs}

扩展自己的请求方法不需要在客户端注册。厂商请求类型继承 `mcp.types.Request`，通过 `client.session.send_request` 发送，如[提供自己的方法](#serving-your-own-methods)所示。补充一点：当某个参数键必须放进 `Mcp-Name` 头（tasks 之类的扩展规范对其动词有此要求）时，请求类型要声明 `name_param`：

```python title="client.py" hl_lines="22-25 46-47"
--8<-- "docs_src/extensions/tutorial007.py"
```

会话在每条发送路径上都会把 `params["jobId"]` 镜像到 `Mcp-Name` 中，值缺失时会明确报错，而不是悄悄漏掉一个必需的头。

## 扩展不能做什么 {#what-an-extension-cannot-do}

贡献面是有意**封闭**的。服务器端：设置、工具、资源、方法、一个 `tools/call` 拦截器。客户端：设置、结果认领、通知绑定。扩展不能：

* **伸手进宿主内部。**它只声明数据，不持有服务器或客户端的引用。
* **替换核心行为。**规范方法和核心结果标签在构造时就被拒绝（`initialize` 更是被运行器直接保留）；被核心词汇遮蔽的通知绑定则会安静失效并给出一条警告。
* **延迟注册。**`MCPServer(...)` 或 `Client(...)` 返回之后，扩展集合就定了。

如果你在跟这些墙较劲，那你写的不是扩展，而是一个 fork。墙本身就是特性：用户读到 `extensions=[Apps(), Stamps()]`，就知道这两者可能触碰过的**一切**。
