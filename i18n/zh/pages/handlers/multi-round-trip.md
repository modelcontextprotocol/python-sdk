---
translation:
  sections: [74011e683045eea9, 9b64cc175c18b6a9, 4b41be4824030397, e3b1502da786ec33, 71e41161f143c6a9, 9ec2c1eeb8c36378, 8dd027377d46448b, f81491125dcbfe8b]
  tool: 1
---
# 多轮往返（multi-round-trip）请求 {#multi-round-trip-requests}

有时一个工具没法在一次往返内完成。它需要只有用户才有的东西：一个选择、一次确认、一份凭据。

在 2026-07-28 之前，服务器靠**回调**拿到它：在处理原请求的中途，自己向客户端发起一个请求——一次征询（elicitation）、一次采样（sampling）调用。2026-07-28 规范移除了这条反向通道（back-channel）。

取而代之的是，服务器**返回**。

## 返回，而不是回调 {#return-dont-call-back}

服务器用 **`InputRequiredResult`** 而不是 `CallToolResult` 来响应 `tools/call`。起作用的是其中两个字段：

* **`input_requests`**：服务器还需要什么，形式是一个 dict，键是服务器自己选的名字。每个值是一个 `ElicitRequest`、`CreateMessageRequest` 或 `ListRootsRequest`。
* **`request_state`**：一个不透明的令牌。客户端在重试时原样回传。只有你的服务器会读它。

客户端满足每个请求，然后**再次调用同一个工具**，把答案放在 `input_responses` 里，令牌放在 `request_state` 里。服务器这时拿到了缺的东西，返回一个普通的 `CallToolResult`。

整个协议就是这样。每一轮都是客户端发给服务器的普通请求，没有任何东西反方向流动。

## 服务器端 {#the-server-side}

在 `@mcp.tool()` 上很少需要手动构造它：声明一个向用户提问（`Elicit`）、对客户端的 LLM 采样（`Sample`）或列出客户端根目录（roots，`ListRoots`）的依赖，SDK 就会替你返回 `InputRequiredResult`；这种形式见 **[依赖](dependencies.md)** 页面。两种形式不能混用：一次调用只有一条 `input_responses`/`request_state` 通道，所以使用 `Resolve(...)` 参数的工具不能再从函数体返回 `InputRequiredResult`。声明了 `InputRequiredResult` 返回类型的会在注册时被拒绝（`InvalidSignature`），没声明的则在运行时让调用失败。手动形式是**低层** `Server`，它的 `on_call_tool` 处理函数可以返回两种结果类型中的任意一种：

```python title="server.py" hl_lines="43-46"
--8<-- "docs_src/mrtr/tutorial001.py"
```

* `on_call_tool` 的类型标注是 `-> CallToolResult | InputRequiredResult`。返回后者就是服务器端的全部 API。
* 第一次调用时 `params.input_responses` 是 `None`，于是守卫条件成立，处理函数提问而不是回答。
* 重试时，客户端发来的 `ElicitResult` 就在服务器在 `input_requests` 里用过的**同一个键**（`"region"`）下。

那个文件里的其他内容（显式的 `input_schema`、手工构造的 `CallToolResult`）都是普通的低层 `Server`，详见 **[低层 Server](../advanced/low-level-server.md)**。本页只是多加了第二种返回类型。

## 不止于工具 {#beyond-tools}

`tools/call` 并不特殊：在 2026-07-28 下，服务器可以用同样的方式响应 `prompts/get` 和 `resources/read`。在 `MCPServer` 上，`@mcp.prompt()` 函数——或 `@mcp.resource()` **模板**函数——自己返回 `InputRequiredResult`，并从上下文里读取重试带来的答案：

```python title="server.py" hl_lines="20 22 24"
--8<-- "docs_src/mrtr/tutorial004.py"
```

* 第一轮返回 `InputRequiredResult`。重试时，`ctx.input_responses` 在同样的键下保存着答案，函数返回它的普通结果——这里是提示词消息，对模板资源来说是资源内容。
* 你设置的 `request_state` 在上线路之前会被密封，回传时会被校验，和服务器上的其他状态一样；下面的 **[保护 `requestState`](#protecting-requeststate)** 说明密封带来了什么、什么时候需要配置密钥。
* 当依赖形式不合适时，`@mcp.tool()` 函数也可以用同样的方式直接返回这个结果。
* 静态的 `@mcp.resource()` 函数不参与：它们不接收 `Context`，所以永远读不到重试。只有模板资源能提问。
* 下文关于协议时代的规则原样适用：在 2026 之前的会话上返回 `InputRequiredResult`，就是警告里描述的那个 `-32603`。

## 客户端 {#the-client-side}

`Client` 替你跑这个循环。

注册服务器可能用到的回调（`elicitation_callback`、`sampling_callback`、`list_roots_callback`），然后调用工具。`InputRequiredResult` 到达时，`Client` 把 `input_requests` 里的每一项分派给对应的回调，带着答案和回传的 `request_state` 重试，一直持续到拿回 `CallToolResult`：

```python title="client.py" hl_lines="11 12"
--8<-- "docs_src/mrtr/tutorial003.py"
```

* 那个 `elicitation_callback` 正是 2026 之前的服务器通过反向通道发出的 `elicitation/create` 会命中的那个。`sampling_callback` 之于 `sampling/createMessage`、`list_roots_callback` 之于 `roots/list` 也一样：在 2026-07-28 下，独立的服务器->客户端 RPC 没有了，但完全相同的 `ElicitRequest` / `CreateMessageRequest` / `ListRootsRequest` 载荷搭在 `input_requests` 里，分派给同样的三个回调。一套回调服务两个时代。
* `call_tool` 返回普通的 `CallToolResult`。中间的轮次对调用方不可见。
* `get_prompt` 和 `read_resource` 驱动同一个循环。

!!! check
    去掉回调，循环在第一轮就会失败：SDK 的占位回调会用错误回答每一次征询，`call_tool` 抛出 `MCPError`，消息是“Elicitation not supported”。

循环是有界的。`Client(..., input_required_max_rounds=10)` 是默认上限；服务器超过上限还在返回 `InputRequiredResult`，`call_tool` 就会抛出异常。如果某一轮只带 `request_state` 而没有 `input_requests`，`Client` 会在重试前短暂休眠（50 ms 起翻倍，上限 250 ms），这样一个只是在说“还没好”的服务器不会被忙轮询。

### 自己驱动循环 {#driving-the-loop-yourself}

自动循环对单进程客户端已经够用。遇到以下情况，改为自己掌控循环：

* 客户端是**分布式**的：把问题呈现给用户的进程不是调用 `call_tool` 的进程，所以重试由另一个 worker 发出。`request_state` 是跨越这条边界、经由你自己的存储携带的可持久化令牌；`input_responses` 是另一侧连同它一起发回的东西。
* 想**检查**每一轮：记录或审计每一个 `input_requests` 项，拒绝某些类型的请求，或在两轮之间应用自己的退避策略。
* 想要**挂钟时间**的上限而不是轮数上限：把自己的循环包在 `anyio.fail_after(...)` 里，而不是依赖 `input_required_max_rounds`。

下探到底层 session，在那里 `allow_input_required=True` 直接把联合类型交给你：

```python title="client.py" hl_lines="12 13 19"
--8<-- "docs_src/mrtr/tutorial002.py"
```

* `client.session.call_tool(..., allow_input_required=True)` 把返回类型放宽为 `CallToolResult | InputRequiredResult`。`isinstance` 负责把它重新收窄。
* `request_state` 现在在你手上。两轮之间把它记下来，对话就能从一个全新的进程恢复。
* 对 `input_requests` 里的每一项，在 `input_responses` 的**同一个键**下放一个 `InputResponse`。`fulfil` 是放你的 UI 的地方；这个例子把答案写死了。
* 每一轮都是同一个工具名、同样的 `arguments`。重试是把原调用再执行一遍，不是一个新方法。

## 保护 `requestState` {#protecting-requeststate}

上面一直把 `request_state` 当作回传，在线路上它也确实只是这样。但客户端在两轮之间持有它（跨进程记下来正是上一节认可的做法），所以回来的东西是**客户端提供的输入**：它可能被改动、过期，或者干脆是从另一次调用里搬来的。规范要求，只要这个状态能影响授权、资源访问或业务逻辑，服务器就必须对它做完整性保护，并在校验失败时拒绝这一轮。

`MCPServer` 默认就保护它。每个服务器都会用进程启动时生成的密钥密封发出的 `requestState`，并校验每一次回传——解析器状态和手工构造的状态都一样。你什么都不用配置，写的是明文，读的也是明文；线路上只会出现一个不透明的加密令牌。

默认密钥与进程同生共死，这是部署到单进程之外前必须知道的一件事：

```python
from mcp.server.mcpserver import MCPServer, RequestStateSecurity

# Multi-instance or restart-surviving: one or more shared secret keys (>= 32 bytes each).
mcp = MCPServer("fleet", request_state_security=RequestStateSecurity(keys=[key]))
```

* **默认（不配置）**适合单进程：stdio，或恰好一个 HTTP worker。落到另一个 worker、负载均衡器后面的另一个实例、或重启后的同一服务器上的重试，是用那个进程没有的密钥密封的——客户端会收到下面那条固定的拒绝，必须从头开始这个流程。
* 只要重试可能到达**另一个实例**（多 worker 的 `uvicorn`、负载均衡的 HTTP）或必须熬过重启，就需要 **`keys=[...]`**：每个实例都能校验任何同伴签发的东西。同样的机制，只是用你的密钥替代生成的密钥。
* 要用自己的加密方案，比如 KMS 或已有的令牌服务，传 `RequestStateSecurity(codec=...)` 而不是 `keys`；下面的 **[自带加密](#bring-your-own-crypto)** 说明了契约。

### 密封里带了什么 {#what-the-seal-carries}

无论默认还是配置过，线路上的 `requestState` 都是一个加密且经过认证的令牌。你的代码永远看不到它：处理函数和解析器写明文、读明文（`ctx.request_state`）；SDK 在发出时密封，在收到时校验。除了完整性，每个令牌还绑定到：

* **一个时间窗口。** 每一轮都用新的过期时间重新密封，所以 `RequestStateSecurity(ttl=...)`（默认 600 秒）限制的是每轮的思考时间，而不是整个流程。
* **已认证的主体。** 当请求携带一个经 SDK 校验的 OAuth 访问令牌时，状态绑定到该令牌的客户端、颁发者和 subject：为一个用户签发的状态在另一个用户下会失败，即使两个用户共用一个 OAuth 客户端。不提供 subject 的校验器会让绑定退化为仅客户端身份，而在基于 URL 的客户端 ID 下，这个身份由该客户端软件的所有用户共享。当认证在 SDK 之外终结（前置代理），或传输未经认证时，没有主体可绑定，这项检查不起作用，除非 `RequestStateSecurity(bind_principal=...)` 从你自己的身份信号提供一个。无论你的令牌校验器提供哪些组成部分，都必须一致地提供：一个在某些请求上包含 subject、在另一些请求上省略它的校验器会在流程中途改变主体，进行中的轮次会被拒绝。
* **发起的请求。** 方法、工具或提示词名称（或资源 URI），以及参数的摘要。针对不同工具、不同参数或不同方法重放的令牌会失败。
* **所问的确切问题。** 每个解析器答案都钉在客户端看到的那个渲染后的问题上，无论是它第一次到达的那一轮，还是之后复用已记录答案的时候。换了措辞的消息或改过的 schema 重新部署后，服务器会重新提问，而不是吞下一个过期的答案。同样的钉住也有反面：要从工具的参数派生消息，而不是从每次调用的数据派生。用时间戳或实时汇率构造的消息每一轮渲染都不一样，于是每个已记录的答案看起来都过期了，服务器一直重新提问，直到客户端的轮数上限结束这次调用。

这些全是 SDK 的工作，不是你的；如果你自带 codec，也不是 codec 的。

### 轮换密钥 {#rotating-keys}

`keys[0]` 密封新状态；列表里的每个密钥都参与校验。零停机轮换分三个阶段，每个阶段完全铺开后再进入下一个：

```python
RequestStateSecurity(keys=[OLD, NEW])  # 1: every instance learns to verify NEW; OLD still mints
RequestStateSecurity(keys=[NEW, OLD])  # 2: NEW mints; in-flight OLD state keeps verifying
RequestStateSecurity(keys=[NEW])       # 3: one ttl after phase 2 is fully out, retire OLD
```

永远不要先提升签发密钥：用某个实例还不能校验的密钥签发，会在铺开途中丢掉进行中的轮次。

密钥的作用域是单个服务。密封的信封还把服务器的名字作为 audience 声明带上，所以另一个恰好共用密钥的服务签发的令牌照样会被拒绝。这个声明的区分度取决于名字，所以被赋予显式策略的服务器必须有一个真实的名字，或者设置 `RequestStateSecurity(audience=...)`——没有名字的会在构造时抛出异常。`audience=` 也服务于有意为之的多服务拓扑，即一个服务必须接受另一个服务签发的状态。（不配置的默认情形不受此限：它的密钥从不离开进程，audience 声明没有什么可补充的。）

### 自带加密 {#bring-your-own-crypto}

`RequestStateSecurity(codec=...)` 接受任何带有 `seal(bytes) -> str` 和 `unseal(str) -> bytes`、并对任何不是自己签发的令牌抛出 `InvalidRequestState` 的对象。典型形态是基于 KMS 的信封加密：启动时解包一次数据密钥，每个令牌的加解密留在本地：

```python title="server.py" hl_lines="12 26-27 34-35 38"
--8<-- "docs_src/mrtr/tutorial005.py"
```

TTL、主体绑定和请求绑定**不是** codec 的工作：对每个 codec，SDK 都在 `seal` 之前把它们印进载荷，在 `unseal` 之后重新校验。codec 唯一的义务是完整性（被篡改就抛出异常），以及最好有机密性。

### 校验失败时 {#when-verification-fails}

每一个入站失败，无论是被篡改、过期、针对不同请求或主体重放，还是用本服务器不认识的密钥密封的，得到的都是同一个回答：

```json
{"code": -32602, "message": "Invalid or expired requestState"}
```

所有原因都是同一条固定消息，这样线路上永远不会泄露哪项检查失败了；真正的原因写进服务器日志。`tools/call`、`prompts/get` 和 `resources/read` 上每一个入站的 `requestState` 都会被检查，包括发给一个从不签发状态的处理函数的。实践中最常见的拒绝不是攻击者——而是默认的进程本地密钥遇上了来自重启之前或另一个实例的重试；客户端重新开始流程，需要在意时 `keys=[...]` 就是解法。

### 手工构造的状态 {#hand-built-state}

你自己设置的 `request_state`（从工具、提示词或资源模板函数返回 `InputRequiredResult`）由与解析器状态相同的机制密封和校验，代码一行不用改：写明文、读明文，上面的每一项绑定都适用。

即使配置过，SDK 唯一无法替你钉住的是问题的身份：它不知道你状态里的某个答案属于**你的**哪一个问题。如果按问题为键存答案，就在状态里放进你自己的问题标识符，并在重试时检查它。

低层 `Server` 是什么都不自带的那一层：和 `MCPServer` 不同，在你自己加上这道边界之前什么都不会被密封，在那之前你的 `request_state` 按原样跨越线路。一行代码的启用方式见 **[低层 Server](../advanced/low-level-server.md#the-other-handlers)**。

## 一个 2026-07-28 的结果 {#a-2026-07-28-result}

`InputRequiredResult` 只存在于协议版本 **2026-07-28**。内存中的 `Client(server)` 替你协商它；走线路时，`mode="auto"` 会发现它。连接之后，`client.protocol_version` 告诉你拿到的是什么。

!!! warning
    2026 之前的会话没有地方放 `InputRequiredResult`。在 `mode="legacy"` 连接上从处理函数返回一个，运行器无法把它序列化到协商好的版本；客户端收到的是 `-32603`“Handler returned an invalid result”错误。同时服务两个时代的服务器在用它之前必须检查 `ctx.protocol_version`。

!!! info
    **URL 模式的征询**在 2026 连接上走的正是这套机制。`input_requests` 里的那一项是一个 params 为 `ElicitRequestURLParams` 的 `ElicitRequest`；用户完成带外流程，你的客户端重试调用。同一个循环，没有新 API。高层服务器那一半见 **[征询](elicitation.md)**。

## 回顾 {#recap}

* 在 2026-07-28 下，调用中途需要输入的服务器**返回**一个 `InputRequiredResult`。它从不向客户端发起请求。
* `input_requests` 是它需要的东西。`request_state` 是只有服务器会读的不透明恢复令牌。
* `Client` 替你跑重试循环：注册 `elicitation_callback` / `sampling_callback` / `list_roots_callback`，`call_tool` 就返回普通的 `CallToolResult`。`input_required_max_rounds`（默认 10）给它设了上限。
* 要检查或持久化轮次，用 `client.session.call_tool(..., allow_input_required=True)`，自己掌控 `while isinstance(result, InputRequiredResult)` 循环。
* 在 `@mcp.tool()` 上，一个向用户提问的依赖会替你产生这个结果（**[依赖](dependencies.md)**）；**低层** `Server` 是手动形式。
* 提示词和资源也参与：`@mcp.prompt()` 或模板 `@mcp.resource()` 函数自己返回 `InputRequiredResult`，重试时读取 `ctx.input_responses`。
* `requestState` 回来时是客户端提供的输入，所以 `MCPServer` 默认用进程本地密钥密封它——解析器状态和手工构造的状态都一样；多实例部署传入 `RequestStateSecurity(keys=[...])`（或自定义 codec），让每个实例都能校验同伴签发的东西。密封把每个令牌绑定到一个时间窗口、发起的请求，以及已认证的主体——当请求携带经 SDK 校验的认证信息，或 `bind_principal=` 提供了你自己的身份信号时（**[保护 `requestState`](#protecting-requeststate)**）。

这就是取代服务器发起的采样以及其余推送式反向通道的机制；见 **[已弃用的功能](../deprecated.md)**。
