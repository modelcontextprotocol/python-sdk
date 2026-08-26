---
translation:
  sections: [28221886b198784f, f88ea1f1614f3a1d, ce926d686730b6d0, 3be24f8ad8bb5ab9, 3fad24032b2224ff, f25a7f860e579ecb, e758745df6fb7b0a]
  tool: 1
---
# 部署与扩展 {#deploy-scale}

你的服务器已经能跑了。现在它需要一个真实的主机名，后面还要挂不止一个 worker。

这些事几乎都不归 MCP 管。ASGI 服务器、进程管理器、负载均衡器都由你自己带。这一页只讲确实归 MCP 管的那几件事：一个卡住所有部署的设置，以及"不止一个 worker"会改变 SDK 行为的两个地方。

## 首先：Host 白名单 {#before-anything-else-the-host-allowlist}

`streamable_http_app()` 无从知道自己会被放在哪个主机名后面，所以它假设最安全的答案：localhost。没有传 `transport_security=` 时，应用会开启 **DNS 重绑定防护**，只接受 `Host` 头为 `127.0.0.1:<port>`、`localhost:<port>` 或 `[::1]:<port>` 的请求。如果有 `Origin` 头，它必须是同一地址的 `http://` 形式。在你自己的机器上这正合适：它能阻止恶意网页通过一个重绑定到 `127.0.0.1` 的 DNS 名称操纵你的本地服务器。

部署到真实主机名后面，同样的默认值会拒绝**所有请求**，直到你另有说明。这项检查在任何 MCP 逻辑之前运行，所以你写的东西根本不会被调用：

```text
421 Misdirected Request    Invalid Host header      the Host is not in the allowlist
403 Forbidden              Invalid Origin header    the Origin is not in the allowlist
```

解决办法是 `transport_security=`。把你实际对外服务的地址加入白名单：

```python title="server.py" hl_lines="2 13-17"
--8<-- "docs_src/deploy/tutorial001.py"
```

* `allowed_hosts` 的条目是精确字符串：`"mcp.example.com"` 匹配不带端口的 `Host` 头，`"mcp.example.com:*"` 匹配任意端口。两个都要列上。
* `allowed_origins` 只对浏览器有意义，因为别的客户端不发 `Origin`。它是 **[添加到现有应用](asgi.md)** 中 CORS 配置在服务器端的对应项。
* 如果前面有一个已经控制 `Host` 头的反向代理，直接关掉这项检查才是诚实的配置：`TransportSecuritySettings(enable_dns_rebinding_protection=False)`。
* 传一个非 localhost 的 `host=`（例如 `host="mcp.example.com"`）并**不会**把该主机名加入白名单。它只是让 localhost 默认值不再触发防护，结果是所有 Host 和 Origin 都被接受。想表达什么，就用 `transport_security=` 明确说出来。

!!! check
    删掉 `transport_security=security` 参数，照样部署这个应用。它能启动，`/mcp` 能路由，而每一个请求（包括一个普通的 `curl`）都会返回：

    ```text
    HTTP/1.1 421 Misdirected Request

    Invalid Host header
    ```

    在客户端那边你找不到这几个字。`421` 是纯文本的 HTTP 响应，不是 JSON-RPC 错误，所以 MCP 客户端抛出的是一个泛泛的传输错误；它不认可的那个主机名只出现在**服务器**的日志里，是一条警告。一个刚部署好、拒绝所有连接的服务器，在证明是别的原因之前，就是 Host 白名单的问题。**[故障排查](../troubleshooting.md)** 也从这里讲起。

## Worker，以及谁需要粘性 {#workers-and-who-has-to-be-sticky}

主机名能响应之后，就在后面放不止一个 worker。SDK 没有这方面的开关；扩展一个 Starlette 应用和扩展任何 ASGI 应用一样，把对象交给一个会 fork 的东西：

```console
uvicorn server:app --workers 4
```

四个进程，一个套接字。接下来是每个部署都必须回答的问题：**一个请求是否必须到达处理了上一个请求的那个 worker？**

对使用 **2026-07-28** 协议的客户端来说，不需要。现代请求是一个自包含的 POST：前面没有 `initialize` 握手，响应上没有 `Mcp-Session-Id`，第二个请求没有任何东西需要"回到"。路由到任意 worker 即可。

这不是一个需要打开的模式。`stateless_http=True` 看起来像是，但传输层按 `MCP-Protocol-Version` 请求头路由，把现代请求交给现代处理函数，然后就**返回**了。读取 `stateless_http` 的那一行在这个返回**之后**。不是这个标志在 2026-07-28 路径上被忽略，而是根本走不到它。`stateless_http` 只是**旧版**那一支的开关，现代路径从构造上就是无会话的。

对使用规范版本 2025-11-25 或更早的旧版客户端，答案取决于这个标志：

| 客户端的协议版本 | 会话 | 负载均衡器必须做什么 |
| --- | --- | --- |
| **2026-07-28** | 无。`Mcp-Session-Id` 从不设置。 | 什么都不用。任意 worker 处理任意请求。 |
| **2025-11-25 及更早**（默认） | `Mcp-Session-Id`，保存在某一个 worker 的内存里。 | **粘性会话。** 后续请求到达另一个 worker 会得到 `404` "Session not found"。 |
| **2025-11-25 及更早**，加上 `stateless_http=True` | 无。 | 什么都不用。代价是服务器到客户端的反向通道（back-channel）（采样（sampling）、推送式征询（elicitation）、`roots/list`）和可恢复性。 |

粘性会话以及旧版那一支的代价单独有一页：**[服务旧版客户端](legacy-clients.md)**；两个时代本身见 **[协议版本](../protocol-versions.md)**。这里重要的是答案的形状：**在 2026-07-28 上你已经是无状态的，没有什么需要配置。**

这一页剩下的部分，是无状态**并不能**帮你解决的两件事。

## 跨 worker 的 `requestState` {#requeststate-across-workers}

**[多轮往返（multi-round-trip）](../handlers/multi-round-trip.md)** 工具需要客户端去取某样东西（一次确认、一个选择、一份凭据），所以它返回一个问题而不是答案，在重试时完成。两轮之间，客户端持有服务器铸造的一个不透明的 `request_state` 令牌。重试时服务器必须重新打开这个令牌。

**用什么密钥封存的？** 默认是服务器在构造时用 `os.urandom(32)` 生成的那一个。在 `--workers 4` 下就是四次构造、四个进程：四把不同的密钥，没写到任何地方，互不共享，重启即失。

下面是一个先问后做的工具，所在的服务器什么都没配置：

```python title="server.py" hl_lines="14 20"
--8<-- "docs_src/deploy/tutorial002.py"
```

第一轮到达 worker A。worker A 用**它的**密钥封存 `refund:120` 并返回令牌。客户端把问题摆到人面前，得到一个"是"，然后重试。重试是一个全新的 HTTP 请求。

!!! check
    让这次重试到达 worker B。B 尝试解封一个不是它铸造的令牌，做不到，于是拒绝整轮请求。`refund` 从未被调用；客户端得到一个 JSON-RPC 错误：

    ```json
    {
      "code": -32602,
      "message": "Invalid or expired requestState",
      "data": {"reason": "invalid_request_state"}
    }
    ```

    这条消息是**固定的**。过期、被篡改、针对不同参数重放，或者（真实部署中最常见的原因）由兄弟 worker 封存：客户端每次收到的都一样，线路上从不透露是哪项检查失败了。真正的原因是服务器日志里的一条 `WARNING`：

    ```text
    requestState rejected on tools/call: unknown key
    ```

    一个在单 worker 下正常、到两个 worker 时开始**时而**失败的多轮往返工具，就是这个问题。两轮仍然必须到达同一个进程，所以它失败的频率恰好等于负载均衡器把它们分开的频率。

两轮是两个独立的 HTTP 请求，好几种平常的情况都会把它们分开：按请求均衡的代理、中途断开的连接、一次部署或重启、一个持久化了 `request_state` 并从完全不同的进程恢复的客户端（**[自己驱动循环](../handlers/multi-round-trip.md#driving-the-loop-yourself)**）。这些都算"另一个 worker"。

解决办法是一个参数。它有**两**半。

```python title="server.py" hl_lines="1 12 14"
--8<-- "docs_src/deploy/tutorial003.py"
```

* **`keys=[...]`** 是大家都能找到的那一半。给每个实例同一个密钥（至少 32 字节），每个实例就能解封任何兄弟实例铸造的令牌。`keys[0]` 封存，列表中的每一把都能解封，这就是轮换环；**[轮换密钥](../handlers/multi-round-trip.md#rotating-keys)** 讲的是如何不停机地转动它。
* **服务器的名字**是几乎没人找得到的那一半，也是共享了密钥之后跨实例重试仍然失败的原因。每个封存的令牌都把服务器的 `name` 作为 **audience 声明**带上，解封时严格校验。从同一份代码构建的两个实例名字相同，永远不会察觉这一点。把它们命名区分开（`MCPServer(f"billing-{POD}")` 看上去像是良好的可观测性习惯），每一次跨实例重试就会和上面一模一样地被拒绝，不管有没有共享密钥。日志里写的是 `audience` 而不是 `unknown key`；客户端分辨不出区别。

密钥铸造一次，把同一个值交给每个实例。这就是 SDK 自己的错误消息在你传入不足 32 字节时让你运行的命令：

```console
python -c "import secrets; print(secrets.token_hex(32))"
```

!!! warning "相同的密钥，**以及**相同的名字"
    多实例部署两者都必须共享。如果每实例的名字对你来说不可或缺，那就给整个集群一个显式的 audience：`RequestStateSecurity(keys=[...], audience="billing")`。这样每个实例无论叫什么，都在 `"billing"` 下铸造和接受令牌。

关于封存的其余一切见 **[保护 `requestState`](../handlers/multi-round-trip.md#protecting-requeststate)**：它绑定什么、每轮的 `ttl`（默认 600 秒）、自带编解码器、为什么未配置的默认值在 `stdio` 上正合适。这一页的全部贡献是一张两项的清单：**相同的密钥，相同的名字。**

!!! info
    即使你从没写过 `InputRequiredResult`，你也在这条路径上。参数里用了 `Resolve(...)`（**[依赖](../handlers/dependencies.md)**）的工具就是多轮往返工具，SDK 替它铸造并封存 `request_state`。同样的默认密钥，同样的跨 worker 失败，同样的修复办法。

## 跨副本的变更通知 {#change-notifications-across-replicas}

客户端的 `subscriptions/listen` 流是一个长时间存活的响应，所以它整个生命期都钉在一个副本上。在**另一个**副本上发布的 `ctx.notify_resource_updated(...)` 必须能到达它。

两者之间的接缝是 `SubscriptionBus`。你给服务器的总线就是所有发布进入、所有打开的流监听的那一个，所以把同一个总线交给每个副本：

```python title="server.py" hl_lines="2 7 9"
--8<-- "docs_src/deploy/tutorial004.py"
```

扇出的过程完全不关心一个流挂在哪个服务器对象上。持有同一个 `InMemorySubscriptionBus` 的两个服务器已经是这样：在其中一个上打开监听流，在另一个上 `edit_note`，流就能收到。这个内存总线只能跨同一进程内的服务器对象，所以它是模型，不是部署方案：

* 跨真正的进程时，**SDK 没有提供任何能帮上忙的总线。** `SubscriptionBus` 是一个两方法的 `Protocol`（`publish` 和 `subscribe`），你在自己的 pub/sub 后端（Redis、NATS，或任何你已经在跑的东西）上实现它，并作为 `MCPServer(subscriptions=...)` 传入。**[订阅](../handlers/subscriptions.md#scaling-past-one-process)** 有示意代码和契约。
* 总线承载的是四种小的有类型事件，从来不是 JSON-RPC。确认、过滤和流的生命周期都留在 SDK 里，所以你的总线不可能破坏协议；它只能在进程之间搬运事件。
* 流**不可**恢复，事件**不会**重放。丢失一个副本就丢掉它的流；客户端重新监听、重新获取。没有需要共享的事件存储，也没有别的需要配置。这是横向扩展真正只是"多来几份"的唯一一处。

## SDK 不提供什么 {#what-the-sdk-does-not-give-you}

`MCPServer` 是一个协议实现，不是应用服务器。你接下来会去找的那些部署开关是故意缺席的：

* **没有 `workers=`。** `mcp.run("streamable-http")` 启动恰好一个 uvicorn 进程，也永远只会启动一个。多进程就是把 `streamable_http_app()` 交给你本来部署 ASGI 用的东西：`uvicorn --workers`、gunicorn、你平台的进程管理器。这一页刻意不做它们任何一个的教程；它们自己的文档比这里照抄一份要好。
* **没有健康检查路由。** `@mcp.custom_route("/health", methods=["GET"])` 就是全部答案，而且即使服务器其余部分有认证，它也从不认证。这对存活探针是对的，对任何私密内容是错的。**[添加到现有应用](asgi.md#custom-routes)** 有一个示例。
* **没有生产设置对象。** `MCPServer` 上没有地方写超时、TLS、优雅关闭或连接数限制，因为这些都不是它的职责。它们属于你的 ASGI 服务器，在那里配置。**[运行你的服务器](index.md)** 讲了构造函数**确实**接受的那几个设置。
* **没有自带的 `EventStore`，在 2026-07-28 上也用不着。** 可恢复性是旧版有状态那一支的特性；现代交换是一个 POST、一个响应，没有什么可恢复的。

## 回顾 {#recap}

* 默认情况下，这个应用只响应发往 localhost 的请求。`transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])` 是上线的关卡：在你传入它之前，真实主机名后面的每个请求都是 `421`，原因只在服务器日志里。
* 在 2026-07-28 上没有会话，负载均衡器没有什么可粘的。`stateless_http=True` 是只对旧版有效的开关，因为现代请求在读到这个标志之前就已经被路由并响应了。
* 默认的 `requestState` 密钥是 `os.urandom(32)`，按进程铸造。到达另一个 worker 的多轮往返重试会以 `-32602` “Invalid or expired requestState” 失败。
* 修复办法是 `RequestStateSecurity(keys=[...])` **并且**每个实例使用相同的服务器名字。名字是令牌默认的 audience 声明。相同的密钥，相同的名字。
* 变更通知通过一个共享的 `SubscriptionBus` 跨副本传递。SDK 唯一的实现是进程内的；在你自己的 pub/sub 上实现那个两方法的 `Protocol` 要由你来写。
* 没有 `workers=`，没有健康路由，没有生产设置对象。自带 ASGI 服务器。

真实主机名前面还需要的另一样东西是令牌：**[授权](authorization.md)**。
