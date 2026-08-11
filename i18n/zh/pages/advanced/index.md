---
translation:
  sections: [ca6988b7503cd2d3]
  tool: 1
---
# 进阶 {#advanced}

普通服务器或客户端需要的一切，在上面的各节里都有对应的专题位置。这一节是在 `MCPServer` 的便利层碍事时才用得上的后门：

* **[底层 Server](low-level-server.md)**：`MCPServer` 构建于其上的类。手写模式、`on_*` 处理函数、没有任何替你做的检查，还可以定义你自己的 JSON-RPC 方法。
* **[分页](pagination.md)** 和 **[中间件](middleware.md)**：两件**只能**在底层 `Server` 上做的事。
* **[扩展](extensions.md)** 和 **[MCP Apps](apps.md)**：协议的扩展面。把扩展包组合进服务器，或者自己写一个。

有几样东西你可能理所当然地想在这里找，但它们其实放在实际用到它们的地方：

* **授权**在 **[运行服务器](../run/index.md)** 下，因为服务器是在部署的地方加以保护的。
* **OAuth**、**身份断言**、连接**多个服务器**以及响应**缓存**都在 **[客户端](../client/index.md)** 下。
* **多轮往返（multi-round-trip）请求**和**订阅**在 **[在处理函数内部](../handlers/index.md)** 下，因为两者都是处理函数**做**的事。
* **URI 模板**在 **[服务器](../servers/index.md)** 下，挨着资源。
* **[协议版本](../protocol-versions.md)** 和 **[已弃用功能](../deprecated.md)** 各有自己的顶层页面。

如果不确定自己需不需要这一节，那就是不需要。
