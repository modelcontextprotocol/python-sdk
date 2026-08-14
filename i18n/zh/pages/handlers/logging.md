---
translation:
  sections: [c93a3e1aefd77955, 7851abd5ec54393b, f49d1ca2f330f9cd, c03764bd9dfeef7b, 4a0391691a674ae4, 2df5cd279eabf9f5]
  tool: 1
---
# 日志 {#logging}

在工具里记录日志，和在其他任何 Python 函数里一样：用标准库。

MCP 在协议层面有一个**日志能力**（logging capability）：服务器可以通过 `Context` 对象上的方法，把自己的日志消息作为通知推送给客户端。规范的 2026-07-28 修订版**弃用了这个能力，而且没有提供替代方案**，所以本文档不讲它。哪些内容已弃用、该用什么代替，完整清单见 **[已弃用的功能](../deprecated.md)**。

取而代之的做法，就是你在其他所有 Python 程序里的做法：标准库。

## 一个会记录日志的工具 {#a-tool-that-logs}

```python title="server.py" hl_lines="1 5 13"
--8<-- "docs_src/logging/tutorial001.py"
```

* `logging.getLogger(__name__)` 返回一个以模块名命名的 logger。在文件顶部创建一次即可。
* 在工具内部调用 `logger.info(...)`，和在其他任何函数里一样。不用注入什么，不用 `await` 什么，也没有任何 MCP 特有的东西。

!!! check
    调用这个工具，看看完整的结果：

    ```python
    result.content             # [TextContent(text="Found 3 books matching 'dune'.")]
    result.structured_content  # {'result': "Found 3 books matching 'dune'."}
    ```

    里面哪儿都没有那行日志。日志是给**你**——运维这个服务器的人——看的。模型永远看不到它。如果某些内容应该让模型读到，就 `return` 它。

## 日志去哪了 {#where-it-goes}

对 **stdio** 服务器来说，这个问题比平时更要紧。宿主把你的服务器作为子进程启动，并从它的 **stdout** 读取 MCP 消息。标准错误才是你的。

标准库默认就做对了：日志输出默认写到 `sys.stderr`。你的 `logger.info(...)` 会落在终端里（或者宿主收集子进程 stderr 的任何地方），协议流保持干净。

!!! tip
    不要在 stdio 服务器里 `print()`。`print` 写的是 **stdout**，而 stdout 属于协议。在服务期间，SDK 会把真正被**刷新**（flush）出去的 stdout 转到 stderr，所以它不会破坏线路；但在块缓冲的进程里，`print()` 的内容通常会一直留在 `sys.stdout` 的缓冲区里没有刷新，直到解释器在退出时把它排空——直接排到协议流上。即使被转走了，这一行也是原样混在日志输出当中，没有级别、没有 logger 名称，也没办法过滤。

    `logger.debug("got here")` 同样只是一行的功夫，而且会去到正确的地方。

## 日志级别 {#the-level}

不需要自己调用 `logging.basicConfig()`。构造 `MCPServer` 时已经调用过了：配了一个指向标准错误的 handler，级别就是你通过 `log_level=` 传入的值。所以只要 `MCPServer("Bookshop", log_level="DEBUG")`，就能看到你的 `logger.debug(...)` 输出。

默认值是 `"INFO"`。

`logging.basicConfig()` 永远不会替换已经存在的 handler。如果你在创建服务器之前自己配置了日志，以你的配置为准。

## 试一试 {#try-it}

用 MCP Inspector 运行服务器：

```console
uv run mcp dev server.py
```

在 **Tools** 标签页调用 `search_books`。Inspector 显示的结果只有返回值。这一行

```text
Searching for 'dune'
```

去了标准错误：终端，而不是线路。

!!! info
    如果你真正想要的是**追踪**（每个请求、耗时多久、是否失败），那你要的不是日志行，而是 span。你的服务器已经在产出它们了：SDK 默认就用 OpenTelemetry 追踪每一条消息。见 **[OpenTelemetry](../run/opentelemetry.md)**。

## 回顾 {#recap}

* MCP 协议的日志能力已被 2026-07-28 规范弃用，且没有替代。不要基于它构建。
* 模块级写 `logger = logging.getLogger(__name__)`，工具里写 `logger.info(...)`。整个模式就这些。
* 日志输出永远到不了模型那里。只有你 `return` 的值才会。
* 标准错误是你的；stdout 属于协议。服务期间 SDK 会把已刷新的零散 stdout 转到 stderr，但没刷新的 `print()` 仍可能在退出时排到线路上，而且被转走的行没有任何标记；用 `logging`，它的 handler 每条记录都会刷新。
* `MCPServer(..., log_level="DEBUG")` 设置级别；你先做好的日志配置不会被改动。

告诉已连接的客户端服务器上有东西变了（工具列表、某个资源），见 **[订阅](subscriptions.md)**。
