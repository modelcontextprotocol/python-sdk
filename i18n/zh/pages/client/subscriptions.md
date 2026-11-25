---
translation:
  sections: [8f9558e57f29eee1, a88c587739e0465c, 46ebfd5b325ed041, 4d10b00b57ce4bd9, 2cdb0edd1f59b3e2]
  tool: 1
---
# 订阅 {#subscriptions}

服务器的目录不是固定的。工具会在运行时出现，资源 URI 背后的内容也会变化。客户端通过 `client.listen(...)` 获知这些变化：一个 `subscriptions/listen` 请求，它的响应**就是**流本身。流保持打开，承载客户端要求的那些变更通知。

本页讲的是客户端这一端：打开流、在主流程旁边监听它，以及处理它的各种结束方式。发布变更、过滤以及提供该方法的服务，是服务器那一侧的内容，见“在处理函数内部”下的 **[订阅](../handlers/subscriptions.md)**。这里的示例连接的是在那里构建的 sprint-board 服务器。

## 监听流 {#watching-the-stream}

一个订阅就是一个上下文管理器。进入它会发送请求，把你传入的关键字参数作为订阅过滤器，并等待服务器的确认，所以代码块开始执行时流已经是活动的。

```python title="client.py" hl_lines="15 18 28"
--8<-- "docs_src/subscriptions/tutorial003.py"
```

迭代会产出四种带类型的事件：`ToolsListChanged`、`PromptsListChanged`、`ResourcesListChanged` 和 `ResourceUpdated(uri=...)`。

事件只说明**什么**变了，从不说明**怎么**变的。这就是 `follow_board` 调用 `read_resource` 和 `list_tools` 的原因：事件是重新获取的信号。读取 `event.uri`，不要假定是哪个资源变了：一个过滤器可以列出多个 URI，服务器也可能报告其中某个 URI 的子资源发生了变化。

等待消费的重复事件会合并成一个，重新获取拿到的依然是当前状态。只有完全相同的事件才会合并：两个针对不同 URI 的 `ResourceUpdated` 是两个事件。

这个句柄还有两个属性：

* `sub.honored` 是服务器确认的过滤器：一个 `SubscriptionFilter`，带有你传入的字段，以属性方式读取（`sub.honored.prompts_list_changed`）。`MCPServer` 会满足你要求的每一种类型，所以它会把你的请求原样回显。支持类型较少的服务器确认的也更少，而一个被确认的类型也可能永远不会触发。服务器还可能拒绝整个请求而不是确认它（见服务器页面上的[决定谁可以监听](../handlers/subscriptions.md#deciding-who-may-watch)），这会以请求错误的形式出现。
* `sub.subscription_id` 是 listen 请求的 id，也就是印在这个流每一帧上的那个 id。可以同时打开多个订阅，各自按自己的 id 解复用。

## 不阻塞地监听 {#watching-without-blocking}

`follow_board` 会一直运行到服务器关闭流为止，而这可能永远不会发生，所以单独使用时它会占据你的整个程序。真实的客户端希望监听任务运行在主流程**旁边**：智能体调用工具的同时，监听任务让缓存或 UI 保持最新。

先打开订阅，再启动监听任务，然后继续做自己的事。

=== "asyncio"

    ```python title="app.py" hl_lines="18 20"
    --8<-- "docs_src/subscriptions/tutorial004_asyncio.py"
    ```

=== "trio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_trio.py"
    ```

=== "anyio"

    ```python title="app.py" hl_lines="18 21"
    --8<-- "docs_src/subscriptions/tutorial004_anyio.py"
    ```

!!! note
    `app.py` 从第一个示例导入 `BOARD` 和 `read_board`，本仓库把那个示例保存为 `tutorial003.py`。如果你把渲染出的文件并排保存为 `client.py` 和 `app.py`，就改写成 `from client import BOARD, read_board`。更下面的 `watch.py` 示例也以同样的方式导入 `read_board`。

顺序是关键。没有任何内容会重放，所以在你的流存在之前发布的事件会被错过。进入 `client.listen(...)` 会等待确认，所以从那一刻起的每一个变更都会到达你的监听任务，而你在代码块内获取的快照不可能漏掉任何一个。

在打开的流旁边，请求可以自由运行，无论来自监听任务还是其他任何任务，都在同一个客户端上。因为**重复**的未消费事件会合并，一个繁忙的主流程可能只产生一次重新获取而不是三次。不同的事件不会合并：一个列出许多 URI 的过滤器会为每个 URI 排队一个待处理事件。

要停止监听，离开代码块即可：没有 `unsubscribe` 调用。取消拥有该代码块的任务会替你做到这一点，SDK 会按传输期望的方式取消 listen 请求：在 Streamable HTTP 上，就是关闭该请求的流。一个随应用整个生命周期运行的监听任务永远不会自行返回，所以在关闭时取消它，或者取消它所在任务组的作用域。

## 流会结束 {#streams-end}

流以两种方式之一结束，两者都是普通的控制流。服务器优雅关闭会结束 `async for`；突然断开会抛出 `SubscriptionLost`。

两者的区别在于诊断意义，而不在于接下来该做什么：流没了，没有任何内容会重放，仍然关心的监听任务就重新 listen 并重新获取。

```python title="watch.py" hl_lines="16 20"
--8<-- "docs_src/subscriptions/tutorial005.py"
```

服务器会出于自己的原因优雅地关闭流，包括甩掉积压过多的订阅者，所以干净的结束并不是停止监听的信号。重新 listen 之前先退避。

`SubscriptionLost` 也有一个本地原因。客户端最多保存 1024 个未消费事件，落后到这个程度的消费者会失去订阅，而不是无限制地增长。让 `async for` 的循环体保持简短，把耗时的工作放到别处。

`keep_following` 只捕获 `SubscriptionLost`。进入 `listen()` 还可能抛出 `MCPError`（连接失败，或服务器不提供该方法）、`TimeoutError`（没有收到确认）和 `ListenNotSupportedError`（2026 之前的连接）。决定你的监听任务应该对其中哪些重试：最后一个永远不会自愈。

## 回顾 {#recap}

* 进入 `async with client.listen(...)`；进入时会等待确认，所以之后发布的任何内容都不会漏掉。
* 用 `async for event in sub` 迭代。事件是重新获取的信号，从来不是载荷。
* 先打开订阅，再把监听任务作为任务运行，工具调用在旁边照常进行。
* 干净的结束会停止循环；断开会抛出 `SubscriptionLost`。无论哪种：重新 listen、重新获取，先退避。
* 离开代码块就是取消订阅。

发布这些事件、收窄过滤器以及扩展到单进程之外，是服务器那一侧的内容：**[订阅](../handlers/subscriptions.md)**。同样这些事件也能让客户端缓存保持可信，下一页是 **[缓存](caching.md)**。
