---
translation:
  sections: [60a9de8a0bdaa531, 317bbe7e4355cdcc, a61d660c8029e04a, 8f7e82fcb88df8a9, b165db51249ff8ed, 266f56fb798068a4, 7c0e57030b622139, df18d7c2417a9883]
  tool: 1
---
# 订阅 {#subscriptions}

服务器的目录不是固定的。工具会在运行时出现，资源 URI 背后的内容也会变化。

**订阅（subscriptions）**就是客户端得知这些变化的方式。客户端发送一个 `subscriptions/listen` 请求，而这个请求的响应**就是**流本身：它保持打开，承载客户端要求的变更通知。

## 在工具里发布变更 {#publish-it-from-the-tool}

你这一边只需要一行：发布变更。

```python title="server.py" hl_lines="20 32"
--8<-- "docs_src/subscriptions/tutorial001.py"
```

* `await ctx.notify_resource_updated("board://sprint")` 会送达每一个订阅了该 URI 的打开中的流。其他人收不到。
* `await ctx.notify_tools_changed()` 会送达每一个要求接收工具列表变更的流。收到它的客户端会再次调用 `tools/list`，这时就能看到 `sprint_report`。
* 同类方法还有 `notify_prompts_changed()` 和 `notify_resources_changed()`。
* 没有订阅者，就没有开销。向空闲的服务器发布是空操作，所以永远不需要检查有没有人在听。只管声明什么变了。

`MCPServer` 替你处理 `subscriptions/listen`。线路上的义务（第一帧是确认、按流过滤、每一帧都带订阅 id）是 SDK 的事。

!!! check
    在线路上，一个过滤器里指定了 `board://sprint` 的流，在 `complete_task` 运行之后是这样的：

    ```json
    {"method": "notifications/subscriptions/acknowledged",
     "params": {"notifications": {"resourceSubscriptions": ["board://sprint"]}, "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}

    {"method": "notifications/resources/updated",
     "params": {"uri": "board://sprint", "_meta": {"io.modelcontextprotocol/subscriptionId": "listen-1"}}}
    ```

    注意这条更新**没有**携带什么：看板本身。每一帧都在 `_meta` 下携带 listen 请求的 JSON-RPC id，这个 id 就是订阅 id。它由客户端生成：Python 的 `Client` 用 `"listen-1"` 这样的字符串；其他客户端可能用整数。

## 只给要求的内容 {#only-what-was-asked-for}

过滤器是一份契约。一个请求了工具列表变更和一个资源 URI 的流，只会收到这两类，别的什么都没有。发布一条提示词变更，那个流保持沉默。

`MCPServer` 把资源 URI 当作精确字符串来匹配，所以指定了 `board://sprint` 的流听不到任何关于 `board://sprint/tasks/1` 的消息。规范允许服务器报告已订阅 URI 的子资源上的变更；`MCPServer` 从不这么做，但客户端被设计为要能应对这种情况。

流**不是**的两样东西：

* **它不是重放日志。** 断掉的流就没了，没人连接时发布的事件不会排队。客户端要重新 listen 并重新获取。
* **它不是 2025 的路径。** 调用了 `resources/subscribe` 的客户端由 `ctx.session.send_resource_updated(uri)` 服务。`notify_*` 方法只送达 `subscriptions/listen` 流。

## 决定谁可以观察 {#deciding-who-may-watch}

默认情况下，请求的每一种类别和 URI 都会被接受：任何调用方都可以观察你发布的任何 URI。没有任何东西会去查你的读取处理函数，因为没人在读取——一个会被你的 `files://{name}` 处理函数拒之门外的调用方，仍然可以在 `files://payroll.csv` 上打开一个流，得知它变了，以及什么时候变的。它永远拿不到内容，也无法探测哪些东西存在，因为未知的 URI 同样会被接受，只是永远不会触发。范围窄，但确实存在，所以在多租户服务器发布按用户区分的 URI 之前，先加上门控。

门控是一个中间件。它在 SDK 确认之前看到 `subscriptions/listen` 请求，当调用方要求了任何它无权读取的东西时就拒绝：

```python title="server.py" hl_lines="19-26 29"
--8<-- "docs_src/subscriptions/tutorial006.py"
```

* `ctx.params` 是原始请求，所以中间件自己把它校验成 `SubscriptionsListenRequestParams`，再读取客户端要求的过滤器。
* 拒绝就是在 `call_next(ctx)` 之前抛出 `MCPError`：客户端收到这个错误而没有流，连接照常继续。让消息保持统一、不点名任何 URI，这样拒绝永远不会证实哪些 URI 是受保护的。
* 一个 `can_access(user, uri)` 同时回答两个问题。资源处理函数在 `resources/read` 时问它；中间件在 `subscriptions/listen` 时问它。把这张表换成数据库或你的 RBAC 系统，两边依然保持一致。
* 这个决定在流的整个生命周期内有效。没有逐事件的重新检查，所以如果调用方的访问权限可能在流途中失效（令牌过期），就在失效时结束该调用方的连接。

完整的中间件契约，包括它还包裹了什么、为什么被标记为暂定，见 **[中间件](../advanced/middleware.md)**。

## 客户端这一端 {#the-client-end}

下面是流另一侧的一个客户端，跟踪着看板：

```python title="client.py" hl_lines="15"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

进入 `client.listen(...)` 会发送请求并等待你的确认，所以代码块开始时流已经是活的，每个带类型的事件都是重新获取的信号，从来不是载荷。这就是一屏之内的整份契约。关于客户端这一端的其他所有内容都在它自己的页面上：在主流程旁边观察、流的结束、以及重新 listen。见“客户端”下的 **[订阅](../client/subscriptions.md)**。

## 扩展到多个进程 {#scaling-past-one-process}

发布通过一个 `SubscriptionBus` 从你的处理函数传到打开的流。默认是内存内的：一个进程，里面的每一个流。在你把多个副本放到负载均衡器后面之前，这就是正确答案；因为到那时，客户端的流被固定在一个副本上，而另一个副本上的发布必须能到达它。

这个接缝由你来实现：在你的 pub/sub 后端之上写两个方法。

```python
from collections.abc import Callable

from redis.asyncio import Redis

from mcp.server.mcpserver import MCPServer
from mcp.server.subscriptions import ServerEvent  # SubscriptionBus is a Protocol: no base class


class RedisSubscriptionBus:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._listeners: dict[object, Callable[[ServerEvent], None]] = {}

    async def publish(self, event: ServerEvent) -> None:
        await self._redis.publish("mcp-events", encode(event))  # to every replica

    def subscribe(self, listener: Callable[[ServerEvent], None]) -> Callable[[], None]:
        token = object()
        self._listeners[token] = listener

        def unsubscribe() -> None:
            self._listeners.pop(token, None)

        return unsubscribe


mcp = MCPServer("Sprint Board", subscriptions=RedisSubscriptionBus(redis))
```

`encode` 由你来写，每个副本上负责解码到达的消息并调用每个已注册 listener 的读取任务也是。listener 是同步的，不得抛出异常，并且在服务器的事件循环上运行。

总线承载的是带类型的 `ServerEvent` 值，四个小的 dataclass，从来不是 JSON-RPC。打标、过滤和流的生命周期都留在 SDK 里，所以总线实现无法破坏协议。它只能在进程之间搬运事件。

要在请求之外发布，就自己构造总线，这样你手里就有它的引用。不传任何东西时 `MCPServer` 会在内部建一个，并且不会暴露它。

```python
from mcp.server.subscriptions import InMemorySubscriptionBus, ToolsListChanged

bus = InMemorySubscriptionBus()
mcp = MCPServer("Sprint Board", subscriptions=bus)


async def tools_reloaded() -> None:
    await bus.publish(ToolsListChanged())  # from a lifespan task, a webhook, anywhere
```

## 低层组合 {#the-low-level-composition}

在低层的 `Server` 上没有任何预先接好的东西，同样的部件三行就能组装起来：

```python title="server.py" hl_lines="8-9 47"
--8<-- "docs_src/subscriptions/tutorial002.py"
```

* 总线归你所有，所以直接向它发布：`await bus.publish(ResourceUpdated(uri=...))`。把它放在处理函数够得着的地方：这里是模块作用域，更大的应用里是生命周期。
* `ListenHandler(bus)` 就是 `MCPServer` 注册的那个处理函数，`on_subscriptions_listen=` 是一个普通的处理函数槽位。在这个槽位里放你自己的可调用对象来实现不同的语义，规范上的义务就转到你身上：先确认，每一帧都打上订阅 id，不投递过滤器之外的任何东西。
* `ListenHandler.close()` 优雅地结束每一个打开的流。每个流收到 listen 请求的结果作为最后一帧，这是规范表达“服务器有意结束了订阅”的方式。它在这些流完成刷新之前就返回，所以在拆掉传输之前给它们一点时间。没有它，流会在客户端断开时结束。

## 回顾 {#recap}

* 客户端用一个 `subscriptions/listen` 请求选择加入，响应就是流。服务它是内置的。
* 你用 `ctx.notify_*` 发布，SDK 负责打标、过滤和生命周期。
* 事件是信号，不是载荷。两端都重新获取。
* 客户端这一端是 `async with client.listen(...)`：详见“客户端”下的 **[订阅](../client/subscriptions.md)**。
* 在低层的 `Server` 上你自己组装同样的部件：一个总线、`ListenHandler(bus)`、`on_subscriptions_listen` 槽位。
* 横向扩展意味着实现 `SubscriptionBus`，两个方法，然后作为 `MCPServer(subscriptions=...)` 传入。

运行提供这一切的服务器，不管是一个副本还是二十个，见 **[部署与扩展](../run/deploy.md)**。
