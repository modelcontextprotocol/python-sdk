---
translation:
  sections: [2efaecdef109a5c5, fcacd3e66b8635a4, 25323d737dcf0261, 4835ed1772f1d113, 137454d469c867f5, 6392596bd6df54f0, 41126fa9c4fe432f, 480b6d7897e30ab4, d83bb682e708dde0, ebbed3449c499db4, 323ef84f6b4bebde, 30fd31be74169d9a, 656943c6cb567218, c2dc3b1007d2e987, 7cf5386b997d04e9, 0b59feed8384456e, 0cba47bae78d04eb, 954dc21efdb532a3]
  tool: 1
---
# 故障排查 {#troubleshooting}

本页的每个标题都是 SDK 产生的某条错误的原文，后面是它的含义和一步到位的修复方法。用浏览器的页内查找在这里搜索 traceback（或服务器日志）的最后一行，只读那一条就够了。

有好几条都基于同一个服务器：一个工具加一个模板化资源，各自遇到不认识的城市都会抛异常：

```python title="server.py"
--8<-- "docs_src/troubleshooting/tutorial001.py"
```

本页引用的错误都是真实的：SDK 自己的测试套件复现了其中每一条。

## `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)` {#exceptiongroup-unhandled-errors-in-a-taskgroup-1-sub-exception}

这不是 MCP 错误，而是 anyio 的噪音。真正的错误在粘贴内容的**最后一行**。

`Client.__aenter__` 会启动一个 task group。anyio 会把所有离开 task group 的东西包进 `ExceptionGroup`，所以**每一个**从 `async with Client(...)` 块逃逸出去的异常，不管是什么，都会装在这样一个 group 里到达：

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.read_resource("weather://Atlantis")
```

```text
  + Exception Group Traceback (most recent call last):
  |   ...
  | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
  +-+---------------- 1 ----------------
    | Exception Group Traceback (most recent call last):
    |   ...
    | ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)
    +-+---------------- 1 ----------------
      | Traceback (most recent call last):
      |   ...
      | mcp.shared.exceptions.MCPError: No forecast for 'Atlantis'.
      +------------------------------------
```

对此有两件事要做：

1. **读最底下。** `MCPError: No forecast for 'Atlantis'.` 才是失败原因；在本页查找**它**的文字。
2. **在块内捕获。** 只有异常**离开** `async with` 时才会出现 `ExceptionGroup`。在块内捕获的话，同一个失败就是普通的 `MCPError`，哪里都没有 group：

```python
async def main() -> None:
    async with Client(mcp) as client:
        try:
            await client.read_resource("weather://Atlantis")
        except MCPError as e:
            print(e)  # No forecast for 'Atlantis'.
```

!!! tip
    **连接**阶段的失败（URL 写错、服务器没在运行、本页后面的 `421`）是从 `async with` 本身逃逸出来的，不存在可以捕获它的“块内”。这类情况就读 group 的最底下。

## `RuntimeError: Client must be used within an async context manager` {#runtimeerror-client-must-be-used-within-an-async-context-manager}

`Client(...)` 只是构建对象。在进入 `async with` 之前什么都没连接，所以每个方法都会拒绝执行：

```python
async def main() -> None:
    client = Client(mcp)
    tools = await client.list_tools()  # RuntimeError
```

进入它。`__aenter__` 就是连接：

```python
async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
```

`__aexit__` 就是断开连接，所以不存在会忘记调用的 `client.close()`。**[测试](get-started/testing.md)** 正是建立在这个模式之上。

## `Error executing tool <name>: <message>` 和 `Unknown tool: <name>` {#error-executing-tool-name-message-and-unknown-tool-name}

你看到的是一个**结果**，不是异常。`call_tool` 没有抛异常，而且对于失败的工具它永远不会抛。

用服务器不认识的城市调用 `forecast`，它抛出的异常会随着一个标记为**成功**的请求返回：

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool forecast: No forecast for 'Atlantis'.")]
result.structured_content  # None
```

`Unknown tool: get_forecast` 是同样的形式，对应服务器从未注册过的名字；错误的参数也以同样的方式被拒绝——对照工具的输入模式校验，在你的函数运行之前。

修复在客户端：**检查 `result.is_error`**。包在 `call_tool` 外面的 `try/except` 一个也抓不到，因为根本没有东西可抓。这是有意为之，也是本页最值得记住的一点：调用是**模型**选的，所以消息交给模型，让它有机会重试。详见 **[处理错误](servers/handling-errors.md)**，包括**确实**会抛异常的 `MCPError` 路径。

## `TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool` {#typeerror-the-tool-decorator-was-used-incorrectly-did-you-forget-to-call-it-use-tool-instead-of-tool}

你写的是 `@mcp.tool` 而不是 `@mcp.tool()`。`tool()` 是一个装饰器**工厂**：没有括号的话，Python 会把你的函数传给它的 `name=` 参数。

```python
@mcp.tool  # <- missing ()
def forecast(city: str) -> str:
    """Today's forecast for one city."""
    return f"{city}: Rain."
```

```text
TypeError: The @tool decorator was used incorrectly. Did you forget to call it? Use @tool() instead of @tool
```

加上括号。同样的手误下，`@mcp.resource(...)` 和 `@mcp.prompt()` 也会报同样的话。

!!! note
    这个异常在模块**被导入**时抛出，早于任何客户端连接。所以如果宿主把你的服务器显示为“启动失败”（或“已断开”），而不是已连接但零个工具，就是这种情形：自己运行 `python server.py`，读 traceback。类型检查器也能抓到它：函数不是合法的 `name=`。

## `Tool already exists: <name>` {#tool-already-exists-name}

两次注册用了同一个工具名。**第一个**胜出，第二个被悄悄丢弃，**服务器日志**里的这条警告是唯一的信号：

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/troubleshooting/tutorial002.py"
```

```text
WARNING mcp.server.mcpserver.tools.tool_manager: Tool already exists: forecast
```

`tools/list` 报告一个 `forecast`，而它是 `forecast_today`。给其中一个改名。`MCPServer(..., warn_on_duplicate_tools=False)` 会压掉警告但不改变结果，所以保持开启。资源和提示词有同样的规则和同样的日志行（`Resource already exists:`、`Prompt already exists:`）。

## 宿主列出了零个工具 {#my-host-lists-zero-tools}

这种情况没有错误字符串，正因如此才难搜。SDK 永远不会从 `tools/list` 里丢掉已注册的工具，所以由内向外排查：

* **服务器到底启动了没有？** 不带括号的 `@mcp.tool` 会在导入时抛异常，而在某些宿主里崩掉的服务器和空服务器看起来很像。自己运行 `python server.py`。
* **工具在宿主运行的那个 `mcp` 上吗？** 另一个模块里的第二个 `MCPServer(...)` 是另一个空服务器。检查宿主的命令实际导入的是哪个对象。
* **有没有两个工具同名？** 那其中一个就没了。在服务器日志里找 `Tool already exists:`。
* **宿主的列表过期了吗？** 启动后新增的工具只会到达处理 `notifications/tools/list_changed` 的客户端。重启宿主是简单粗暴的修复。
* **有没有东西在被转移的窗口之外写了 `stdout`？** 服务期间，SDK 会把**已刷新**的杂散 stdout 转移到 stderr（尽力而为：替换了标准流的环境会原样服务），但更早刷新到 stdout 的输出（包装脚本的 echo、无缓冲进程里导入时的 `print()`），或者在解释器退出时才排空的带缓冲 `print()`，都会落到协议流上。一行垃圾就可能让宿主断开连接，而有些宿主会把这渲染成一个空空如也的服务器。改用 `logging` 模块记录日志。宿主侧检查清单的其余部分见 **[连接到真实宿主](get-started/real-host.md)**。

“无效”的工具名**不**在这个清单上：不合规范的名字会记一条警告，但工具照样注册、照样列出。

## `MCPError: Server returned an error response` {#mcperror-server-returned-an-error-response}

服务器直接拒绝了这个 HTTP 请求，响应体不是 JSON-RPC，所以 python `Client` 除了这个占位消息没有更好的东西可以展示。

最常见的原因远超其他：刚部署的 Streamable HTTP 服务器。不带 `transport_security=` 的 `streamable_http_app()`（以及 `mcp.run("streamable-http")`）默认启用 **DNS 重绑定防护**：只接受 `Host` 头为 localhost 的请求。在笔记本上这是正确的默认值，在真实主机名后面就是错误的：

```python title="server.py" hl_lines="12"
--8<-- "docs_src/troubleshooting/tutorial003.py"
```

部署它，让客户端指向它，连接会在握手时失败：

```python
async with Client("https://mcp.example.com/mcp") as client:
    ...
```

```text
mcp.shared.exceptions.MCPError: Server returned an error response
```

服务器实际发送的词——`421` 和 `Invalid Host header`——永远到不了你这里：421 的响应体没有 `Content-Type: application/json`，所以客户端无法解析。它们在**服务器日志**里，下一步就该看那里：

```text
WARNING mcp.server.transport_security: Invalid Host header: mcp.example.com
```

修复是 `transport_security=`。把实际对外服务的主机名加入允许列表：

```python title="server.py" hl_lines="14-17"
--8<-- "docs_src/troubleshooting/tutorial004.py"
```

!!! check
    改动就这些。完全相同的客户端现在可以连接、协商 `2026-07-28` 并调用 `forecast`。

**[部署与扩展](run/deploy.md)** 讲了每个字段的含义、反向代理的情形，以及部署时其他所有会变的东西。而紧接在下面的 `421 Misdirected Request` / `Invalid Host header` 是从另一侧看到的同一个失败。

## `421 Misdirected Request` / `Invalid Host header` {#421-misdirected-request-invalid-host-header}

这就是 `Server returned an error response`，只不过是从任何**不是** python `Client` 的地方看到的：curl、浏览器的网络面板、反向代理的访问日志，或者别的 SDK。

```bash
curl -i https://mcp.example.com/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

```text
HTTP/1.1 421 Misdirected Request

Invalid Host header
```

`421 Misdirected Request` 是 HTTP 对这个状态码自带的原因短语；`Invalid Host header` 是 SDK 的响应体；而 python `Client` 把同一事件渲染成 `Server returned an error response`。三者是同一次拒绝。检查针对的是**请求携带的 `Host` 头**，不是服务器绑定的地址，所以转发公网主机名的反向代理会和直连客户端一样触发它。

修复和 `Server returned an error response` 下面展示的一样：`transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`。它有两个边界情况值得点名：

* `allowed_hosts` 的条目是精确字符串。`"mcp.example.com"` 匹配裸 `Host` 头，`"mcp.example.com:*"` 匹配任意显式端口。两个都列上。
* 响应体为 `Invalid Origin header` 的 `403` 是针对 `Origin` 头的姊妹检查。它只对浏览器触发（别的东西都不发 `Origin`），`allowed_origins=` 是它的允许列表。

完整的讨论见 **[部署与扩展](run/deploy.md)**，包括什么情况下关掉这个检查才是诚实的配置。

## `RuntimeError: Task group is not initialized. Make sure to use run().` {#runtimeerror-task-group-is-not-initialized-make-sure-to-use-run}

你的 MCP 应用挂载在另一个 ASGI 应用里，而没有任何东西启动它的**会话管理器**。

`mcp.streamable_http_app()` 返回一个 Starlette 应用，它自己的生命周期会启动管理器，而 `uvicorn server:app` 会替你运行那个生命周期。但 Starlette **从不运行被挂载的子应用的生命周期**，所以应用一旦放进 `Mount`，管理器就永远不会启动，第一个请求就炸了：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial005.py"
```

服务器启动了。路由解析了。然后 `uvicorn` 对每个请求都打印这个：

```text
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
RuntimeError: Task group is not initialized. Make sure to use run().
```

客户端看到的是 500。修复是在**宿主**应用上加一个进入 `mcp.session_manager.run()` 的生命周期：

```python
@asynccontextmanager
async def lifespan(app: Starlette) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


app = Starlette(routes=[Mount("/", app=mcp.streamable_http_app())], lifespan=lifespan)
```

这个问题的专门页面是 **[添加到现有应用](run/asgi.md)**，包括一个应用里放多个服务器以及 FastAPI 的情形。同一个类里还有两条相邻的字符串：

* `StreamableHTTPSessionManager .run() can only be called once per instance. Create a new instance if you need to run again.` 管理器是一次性的；两次进入同一个应用的生命周期就会撞上它。
* `mcp.session_manager` 只在调用过 `streamable_http_app()` **之后**才存在，所以先构建路由，只在生命周期内部碰管理器。

## `MCPError: Session not found` {#mcperror-session-not-found}

服务器不认识客户端发来的 `Mcp-Session-Id`，几乎总是因为服务器**重启了**（或者你被路由到了另一个实例）。会话存活在那一个进程的内存里。

没有服务器 bug 可找。HTTP 响应是 `404`，它的响应体**是** JSON-RPC，所以和上面的 `421` 不同，python `Client` 会把这一条原样展示出来：

```json
{"jsonrpc": "2.0", "id": null, "error": {"code": -32600, "message": "Session not found"}}
```

修复是重连：离开 `async with Client(...)` 块，进入一个新的，它会协商一个全新的会话。对于长时间运行的客户端，这意味着在调用外面捕获 `MCPError`，遇到这条消息就重连，而不是在死掉的会话里重试。

如果**没有**重启也发生，说明你跑了不止一个 worker 却没有粘性会话：每个 worker 持有自己的会话表，所以路由到错误 worker 的请求就落到这里。这件事以及它的两种修复（粘性路由，或 `stateless_http=True`）归 **[部署与扩展](run/deploy.md)** 和 **[服务旧版客户端](run/legacy-clients.md)** 管。

对服务器运维方来说，对应的日志行是 `Rejected request with unknown or expired session ID: <id>`。它以 `INFO` 级别记录，所以在常用的 `WARNING` 阈值下看不到。部署后马上成批出现是正常的；每个已连接的客户端都在重连。

## `MCPError: Method not found` {#mcperror-method-not-found}

一侧发送了一个 JSON-RPC 请求，另一侧没有对应的处理函数，`e.error.data` 会给出方法名。常见原因是**时代错配**：某个方法在一个协议修订版里有、在另一个里没有，却发给了处在错误修订版上的对端。比如 `2025` 时代的 `resources/subscribe` 到达 `2026-07-28` 连接，或者固定在 `mode="legacy"` 的客户端发送了 `2026` 独有的 `subscriptions/listen`。哪一侧说什么话的地图在 **[协议版本](protocol-versions.md)**；另一个正当原因（某个可选能力你从没注册处理函数）见 **[补全](servers/completions.md)**。

有一件事**不会**产生这个错误，尽管它是现代协议已移除的请求：工具在 `2026-07-28` 连接上调用 `ctx.elicit()`。服务器根本拒绝**发送**那个请求，所以你得到的是本页后面的 `Cannot send 'elicitation/create': ...`。

## `MCPError: Client did not declare the form elicitation capability required by resolver '<name>'` {#mcperror-client-did-not-declare-the-form-elicitation-capability-required-by-resolver-name}

服务器想问用户点什么，而这个客户端从没说过自己可以被问。

征询（elicitation）解析器在已连接的客户端没有声明表单征询时会一开始就拒绝，`e.error.data` 会准确指出缺了什么：

```json
{
  "code": -32021,
  "message": "Client did not declare the form elicitation capability required by resolver 'server:ask_to_confirm'",
  "data": {"requiredCapabilities": {"elicitation": {"form": {}}}}
}
```

给 `Client(...)` 传入 `elicitation_callback=`。注册回调**就是**能力声明；没有第二个开关：

```python
async def main() -> None:
    async with Client(mcp, elicitation_callback=handle_elicitation) as client:
        result = await client.call_tool("book_table", {"date": "Friday"})
```

**[客户端回调](client/callbacks.md)** 列出了其余几个（`sampling_callback`、`list_roots_callback`），每一个同样都是一种声明。

!!! info
    `-32021` 是 `MISSING_REQUIRED_CLIENT_CAPABILITY`，2026-07-28 规范新增的三个错误码之一。它们都不是异常类：全部以 `MCPError` 的形式到达，要看的是 `e.error.code`。`mcp.types` 导出了这些常量。另外两个是 `-32020` `HEADER_MISMATCH`（某个 HTTP 头和它随附的请求体不一致）和 `-32022` `UNSUPPORTED_PROTOCOL_VERSION`（请求指定了这个服务器不会说的版本）。符合规范的 SDK 客户端产生不了这两个，所以如果看到了，去查在客户端和服务器之间改写请求的那个东西。

## `MCPError: Elicitation not supported` {#mcperror-elicitation-not-supported}

和 `Client did not declare the form elicitation capability ...` 是同一个缺口，只是出自那些不做前置检查的路径：服务器需要一个征询得到回答，而已连接的客户端没有注册 `elicitation_callback`。

在旧版连接上的 `ctx.elicit()` 会见到这一条；在任意连接上，一个被返回的多轮往返（multi-round-trip）问题（**[多轮往返请求](handlers/multi-round-trip.md)**）到达了没有回调来回答它的客户端，也会见到。修复完全一样：给 `Client(...)` 传入 `elicitation_callback=`。不存在哪种“用户没被问到”会以 `decline` 的形式交给你的工具；不能被问的客户端就是一次失败的调用，设计工具时要考虑到这一点。

## `MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.` {#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests}

处理函数试图在请求中途联系客户端，而在这条连接上，这次调用没有任何能承载服务器发出请求的通道。有三种服务器配置会把调用置于这种境地。

**`2026-07-28` 连接：任何传输方式，永远如此。** 现代协议根本没有服务器发起的请求，所以服务器在发送任何东西之前就拒绝了。工具里的 `ctx.elicit()` 是遇到它的经典方式（就在第一次内存测试里，因为 `Client(server)` 不用要求就会协商 `2026-07-28`），而传入 `elicitation_callback=` 什么也改变不了，因为根本没有请求到达客户端让它去回答：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/troubleshooting/tutorial006.py"
```

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("book_table", {"date": "Friday"})
```

```text
mcp.shared.exceptions.MCPError: Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.
```

**`stateless_http=True` 服务器上的旧版连接。** 无状态意味着每个请求自成一个世界：没有会话，没有服务器到客户端的流，于是即使是拥有这些方法的时代，也没有地方可以发送 `elicitation/create`（或 `sampling/createMessage`、`roots/list`）：

```python title="server.py" hl_lines="16 23"
--8<-- "docs_src/troubleshooting/tutorial008.py"
```

**`json_response=True` 服务器上的旧版连接。** `POST` 以一个 JSON 响应体作答，而一个响应体只承载响应本身，所以请求中途的 `ctx.elicit()` 需要的请求级流在这里同样不存在。会话、它的 `Mcp-Session-Id` 以及它的独立流都还在；只有请求级通道没了。

消息会给出它没能发送的方法名。`NoBackChannelError` 是服务器抛出的类，但线路上只承载基类 `MCPError`，所以 traceback 的最后一行是上面这句话，而不是类名。

对 `2026-07-28` 客户端，三种情形的修复都一样：不要在调用中途往回伸手。把问题移进一个**解析器**（或者自己返回一个 `InputRequiredResult`），它就成了**响应**的一部分，而响应是每条连接都能承载的：

```python title="server.py" hl_lines="15-17 21"
--8<-- "docs_src/troubleshooting/tutorial007.py"
```

同样的问题，客户端上同样的 `elicitation_callback`。区别在底层：解析器让服务器从调用中**返回**问题而不是推送它，所以从头到尾没有任何东西从服务器流向客户端。这能救下每一个 `2026-07-28` 客户端，不管服务器处于三种配置中的哪一种。**旧版**客户端单靠这次改写救不了：`2025-11-25` 没有办法返回问题，所以在旧版连接上解析器仍然通过请求级通道发送 `elicitation/create`，也仍然需要一个保留该通道的服务器——既不是 `stateless_http=True` 也不是 `json_response=True`。解析器见 **[征询](handlers/elicitation.md)**；线路上发生了什么见 **[多轮往返请求](handlers/multi-round-trip.md)**。

!!! check
    用 `ctx.elicit()` 的工具没有错，它只是 **2026 之前**的写法。用 `mode="legacy"`（经典的 `initialize` 握手，规范 `2025-11-25` 及更早）连接到一个既不是 `stateless_http=True` 也不是 `json_response=True` 的服务器，它就能工作，因为那里存在服务器到客户端的通道。每个版本有什么，见 **[协议版本](protocol-versions.md)**。

## `MCPError: Invalid or expired requestState` {#mcperror-invalid-or-expired-requeststate}

服务器无法验证客户端回传的 `requestState` 令牌，所以拒绝了这一轮。

`requestState` 是 **[多轮往返](handlers/multi-round-trip.md)** 调用在各段之间携带的不透明恢复令牌。`MCPServer` 在发出时密封它，对每次回传都做验证，而且会验证 `tools/call`、`prompts/get` 和 `resources/read` 上**每一个**入站的 `request_state`，即使处理函数从不生成令牌。所以不是本进程密封的令牌，落到哪里都会被拒绝：

```python
async def main() -> None:
    async with Client(mcp) as client:
        await client.call_tool("forecast", {"city": "London"}, request_state="round-1-from-worker-a")
```

```text
mcp.shared.exceptions.MCPError: Invalid or expired requestState
```

消息是刻意固定的：线路上永远不会透露是哪项检查失败。原因写进**服务器日志**，读它就是全部的诊断：

```text
WARNING mcp.server.request_state: requestState rejected on tools/call: malformed
```

实际会看到的原因：

* **`unknown key`** 是要紧的那一个。默认的密封密钥在进程启动时生成，所以落到**另一个 worker**、负载均衡器后面的另一个实例，或者**重启后**的同一台服务器上的重试，是用本进程从未拥有过的密钥密封的。那不是攻击者；那是默认配置遇上了多于一个进程。
* **`audience`**：令牌由**服务器名不同**的实例密封。名字是密封默认的 audience 声明，所以一组服务器除了共享密钥，还必须共享名字（或显式设置 `RequestStateSecurity(audience=...)`）。
* **`expired`**：这一轮花的时间超过了密封的 `ttl`，即 600 秒，按轮计而不是按调用计。
* **`malformed`** / **`codec error`**：令牌在传输途中被改动，或者压根就不是密封令牌。
* **`request binding`**：令牌回来时带着不同的工具、不同的参数或不同的方法。

多进程的修复是一个参数（每个实例上**相同**的 `keys`）加上一件根本不是参数的事：相同的服务器**名字**（或显式共享的 `audience=`）。

```python
mcp = MCPServer("Weather", request_state_security=RequestStateSecurity(keys=[key]))
```

`keys[0]` 负责密封；列表里的每个密钥都参与验证，这正是零停机轮换得以实现的原因。密封保护了什么以及轮换顺序，见 **[多轮往返请求](handlers/multi-round-trip.md#protecting-requeststate)**；**[部署与扩展](run/deploy.md)** 则完整走一遍双 worker 失败及其两部分的修复。

!!! tip
    `keys=[...]` 会立即拒绝弱密钥，并给出一条格外有用的消息：

    ```text
    ValueError: request-state keys must be at least 32 bytes of secret randomness; keys[0] is 7 bytes. Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
    ```

    照它说的做。

## 还是卡住了？ {#still-stuck}

* 如果 SDK 产生的某条消息不在本页，那本身就是一个值得单独报告的文档 bug。
* 搜索 [issue 跟踪器](https://github.com/modelcontextprotocol/python-sdk/issues)；出现在那里的大多数错误字符串已经有人写过了。
* 什么都没找到？带上完整的 traceback [提一个 issue](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)，或者在 [MCP Contributors Discord 的 #python-sdk-dev](https://discord.gg/6CSzBmMkjX) 里问。

## 回顾 {#recap}

* `ExceptionGroup: unhandled errors in a TaskGroup` 从来都不是真正的错误。读**最后一行**；在 `async with Client(...)` 块**内部**捕获 `MCPError` 可以完全跳过这层包装。
* `call_tool` 不会因为工具失败而抛异常。`Error executing tool ...` 和 `Unknown tool: ...` 是结果：检查 `result.is_error`。
* `Client must be used within an async context manager` -> 用 `async with`。`Use @tool() instead of @tool` -> 加上括号。
* 服务器日志里的 `Tool already exists:` 是两个同名工具合并成一个的唯一迹象。
* 一个 421，三种写法：`Server returned an error response`（python `Client`）、`421 Misdirected Request` / `Invalid Host header`（其他所有地方）、`Invalid Host header: <host>`（服务器日志）。修复：`transport_security=TransportSecuritySettings(allowed_hosts=[...])`。
* `Task group is not initialized` -> 被挂载的应用，其宿主生命周期从未进入 `mcp.session_manager.run()`。
* `Session not found` -> 服务器重启了；重连。
* `Cannot send 'elicitation/create': ... no back-channel ...` -> `ctx.elicit()` 需要一条服务器到客户端的通道：`2026-07-28` 连接永远没有，`stateless_http=True` 拿走了旧版的那条，`json_response=True` 拿走了请求级的那条。用解析器（旧版客户端还需要一个保留该通道的服务器）。它的邻居 `Method not found` 是请求了对方协议修订版里没有的方法。
* `Client did not declare the form elicitation capability ...` 和 `Elicitation not supported` -> 客户端缺少 `elicitation_callback=`。
* `Invalid or expired requestState` 在线路上从不说明原因。服务器日志会说；`unknown key` 意味着要在各 worker 间共享 `RequestStateSecurity(keys=[...])`。
