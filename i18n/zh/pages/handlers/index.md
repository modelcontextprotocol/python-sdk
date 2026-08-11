---
translation:
  sections: [424930166c4bc6f3]
  tool: 1
---
# 在处理函数内部 {#inside-your-handler}

处理函数的参数来自客户端。除此之外它能读到的**其他**一切，以及它运行期间能做的一切，都在这里。

它能读到什么：

* **[Context](context.md)** 是任何处理函数都可以额外要求的那一个参数：当前请求、它的标头、它的会话，以及进度和变更通知这些动作。
* **[依赖](dependencies.md)** 是模型永远看不到的参数，由你自己的函数通过 `Resolve` 填入。
* **[生命周期](lifespan.md)** 讲的是服务器在启动时只构建一次的状态，以及处理函数如何通过 `Context` 拿到它。

它运行期间能做什么：

* 用 **[征询（elicitation）](elicitation.md)** 向用户请求更多输入，以及承载它的 2026-07-28 模式 **[多轮往返请求](multi-round-trip.md)**（multi-round-trip）。
* 用 **[采样（sampling）与根目录（roots）](sampling-and-roots.md)** 向客户端请求一次 LLM 补全或它的工作区文件夹——已弃用，但仍然提供。
* 对耗时的操作报告 **[进度](progress.md)**。
* 用 **[日志](logging.md)** 写日志（写到标准错误，给运维服务器的人看）。
* 用 **[订阅](subscriptions.md)** 告诉已订阅的客户端有东西变了。

如果还没注册过处理函数，先看 **[工具](../servers/tools.md)**。这里的每一页都假设你已经有一个了。
