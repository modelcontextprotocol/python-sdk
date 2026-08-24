---
translation:
  sections: [7be05607887e6853, e7375894888d9750, c36f73fc7e3af13b, 2fec2d7e129e62fe, 809b0e0a7c27295a, b4395a04d2a5d906, 1a436007f5f54779, c6b2078ed1e63ba5]
  tool: 1
---
# 错误处理 {#handling-errors}

工具失败有三种方式，SDK 对每一种的处理都不一样。

抛出 `ToolError`，看到你消息的是**模型**。抛出 `MCPError`，看到它的是**协议**。抛出其他任何东西就是崩溃：模型只知道调用失败了，traceback 进你的日志。

这一页讲的就是怎么选。

## 模型能纠正的错误 {#an-error-the-model-can-fix}

拿一个查东西的工具来说，让它查不到：

```python title="server.py" hl_lines="2 12-13"
--8<-- "docs_src/handling_errors/tutorial001.py"
```

`ToolError` 来自 `mcp.server.mcpserver.exceptions`，是工具告诉模型出了问题的方式。

用一个书目里没有的书名去调用它，看看结果：

```python
result.is_error            # True
result.content             # [TextContent(text="Error executing tool get_author: No book titled 'Nothing' in the catalog.")]
result.structured_content  # None
```

* 请求**成功了**。有一个结果；调用方这边什么也没抛出。
* `is_error` 为 `True`，你的消息（前面加了工具名）就在 `content` 里，正是模型读取的位置。
* `structured_content` 为 `None`。失败的调用没有返回值可供结构化。

这就是**工具错误**，而且它几乎总是你想要的效果。

调用工具的是模型，参数也是它挑的。所以工具错误就是对话里的一个回合：模型读到“No book titled 'Nothing' in the catalog.”，发现自己猜错了书名，就换个更好的再调一次。你只写了一个 `raise`，就得到了一个会自我纠正的智能体。

在服务器上，一个 `ToolError` 就是日志里的一行 `INFO`，没有 traceback。这是你预料之中的，所以没什么可查的。

!!! tip
    永远不要从工具里 `return` 错误消息。返回的字符串带的是 `is_error=False`，所以在模型（以及每个客户端 UI）看来，工具运行正常，那个字符串就是答案。要 `raise`。这个标志才是信号。

## 模型纠正不了的错误 {#an-error-the-model-cannot-fix}

现在把 `ToolError` 换成 `MCPError`。

```python title="server.py" hl_lines="1 3 14"
--8<-- "docs_src/handling_errors/tutorial002.py"
```

`MCPError` 是 SDK 的**协议错误**。它是工具包装层唯一**不**捕获的异常：它会向上传播，整个 `tools/call` 请求以一个 JSON-RPC 错误失败，而不是返回结果。

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog."
}
```

* **没有结果**。没有 `content`，没有 `is_error`：模型没有任何东西可读。
* 收到这个错误的是**宿主**应用，和工具根本不存在时的情形一样。
* `code`、`message` 和 `data` 原封不动地送达。`INVALID_PARAMS` 就是 `-32602`；`mcp.types` 把它和其他 JSON-RPC 错误码（`INVALID_REQUEST`、`INTERNAL_ERROR`……）作为常量导出，这样你永远不用手写魔法数字。

!!! check
    同样的查找，同样没查到，但这次调用在客户端一侧**抛出了异常**，而不是返回：

    ```text
    mcp.shared.exceptions.MCPError: No book titled 'Nothing' in the catalog.
    ```

    第一个版本递给模型一句它能据此应对的话。这个版本什么也没给。对 `get_author` 来说这只会更糟，而这正是下一节要讲的重点。

## 该抛哪一个 {#which-one-to-raise}

两条路径回答的是两个不同的问题。

* **抛出 `ToolError`**，对应**执行**层面的失败：工具想做的事没做成。调用是模型选的，所以后果也该让模型看到，给它补救的机会。拼错的书名、超时的上游 API、不存在的数据行：全是工具错误。
* **抛出 `MCPError`**，对应**请求本身**就该被拒绝的情况：客户端缺少工具所依赖的某项能力，服务器当前的状态没法为任何人服务，调用方跳过了某个必需步骤。这些问题模型怎么重试都修不好，所以把消息交给它没有任何好处。

一个问题就能定夺：**换个更聪明的模型，能避免这个问题吗？** 能 -> `ToolError`。不能 -> `MCPError`。

按这个标准，第二版 `get_author` 选错了：换个更好的书名就能解决，所以模型理应看到那条消息。它放在这里是为了让你看清机制，而不是推荐这种写法。

!!! info
    `MCPError` 通过 `from mcp import MCPError` 导入，接受 `code`、`message` 和可选的 `data` 载荷。你往里放什么，客户端就收到什么：SDK 会把抛出的 `MCPError` 原样转发，不做任何清理。

## 任何其他异常 {#any-other-exception}

现在把检查去掉，让字典查找自己失败：

```python title="server.py" hl_lines="11"
--8<-- "docs_src/handling_errors/tutorial004.py"
```

`CATALOG[title]` 抛出 `KeyError`。这不在你的计划之内，所以 SDK 把它当作崩溃：

```python
result.is_error  # True
result.content   # [TextContent(text="Error executing tool get_author")]
```

调用仍然返回 `is_error=True`，所以模型知道它失败了，可以继续往下走。它拿不到的是异常的文本：你代码里的一个 `KeyError`，或者隔着三层库的某个驱动吐出的一堆 SQL，都可能暴露服务器的内部细节，所以它永远不会离开服务器。

拿到它的是你。服务器以 `ERROR` 级别记录这次崩溃，附带完整的 traceback，消息是 `Tool 'get_author' raised an unexpected exception`。所以一个设在 `WARNING` 级别的生产日志，遇到每个 `ToolError` 都保持安静，一旦真有东西坏了就会出声。

## 不存在的资源 {#a-resource-that-doesnt-exist}

资源也划出同样的界线，并为常见情况自带了一个具名异常。

```python title="server.py" hl_lines="2 13"
--8<-- "docs_src/handling_errors/tutorial003.py"
```

`books://{title}` 是一个**模板**。它能匹配**任何**书名，所以“URI 格式正确”和“这本书存在”是两个不同的问题，而第二个只有你的函数能回答。

答案为否时，抛出 `ResourceNotFoundError`。SDK 会把它转成规范为缺失资源指定的那个协议错误：`-32602`，请求的 URI 放在 `data` 里，让客户端知道失败的是**哪一次**读取。

```json
{
  "code": -32602,
  "message": "No book titled 'Nothing' in the catalog.",
  "data": {"uri": "books://Nothing"}
}
```

注意这里没有 `is_error=True` 式的“半个结果”。资源读取要么返回内容，要么失败：资源只有协议这一条路径。`ResourceError` 是同样的东西，用于不属于“未找到”的失败（`-32603`，带你的消息），两者在日志里都是一行 `INFO`。除 `MCPError` 之外的任何其他异常都是崩溃：客户端收到只写明 URI 的 `-32603`，traceback 以 `ERROR` 级别进你的日志。模板以及资源的其他方方面面，详见 **[资源](resources.md)**。

## 你永远不用抛的错误 {#errors-you-never-raise}

不合法的参数根本到不了你的函数。

给 `get_author` 传一个不是字符串的 `title`，SDK 会在调用你**之前**就对照输入模式把它拒掉，得到的同样是模型能读懂并改正的那种 `is_error=True` 工具错误。**[工具](tools.md)** 用一个 `Field(le=50)` 约束演示了同样的拒绝。

这意味着有一整类 `raise` 语句不用你写：不要重复校验自己的类型注解。

!!! info
    这一页上**客户端**看到的一切，你写测试时用的内存中的 `Client` 看到的也一模一样。就连 `raise_exceptions=True` 也不会把失败工具的异常交还给调用方：等那个标志能起作用的时候，你的异常早已是 `is_error=True` 的结果了。对结果做断言。如果需要崩溃的 traceback，它在服务器的日志里，pytest 的 `caplog` 能捕获到。这个模式详见 **[测试](../get-started/testing.md)**。

## 回顾 {#recap}

* 在工具里抛出 **`ToolError`** -> 调用返回 `is_error=True`，你的消息在 `content` 里。模型读到后可以重试。
* 抛出 **`MCPError`** -> 调用本身以 JSON-RPC 错误失败。模型什么也看不到；由宿主处理。`code`、`message` 和 `data` 原封不动地保留。
* 决定性的问题：“换个更聪明的模型，能避免这个问题吗？”能 -> `ToolError`。不能 -> `MCPError`。
* 任何**其他异常**都是崩溃 -> `is_error=True`，模型只看到 `Error executing tool <name>`，你拿到一条带 traceback 的 `ERROR` 记录。
* 资源处理函数抛出 `ResourceNotFoundError` -> 协议的 `-32602`，URI 在 `data` 里。
* 不合法的参数在你的函数运行之前就会对照模式被拒掉；这些不用你 `raise`。
* 导入：`from mcp import MCPError`、`from mcp.server.mcpserver.exceptions import ToolError, ResourceError, ResourceNotFoundError`，以及来自 `mcp.types` 的错误码常量。

错误处理完毕。服务器**对外暴露**的内容就是这些。每个处理函数在运行期间能读到什么、又能反过来对客户端做什么，是下一部分的内容：**[在处理函数内部](../handlers/index.md)**。

你最有可能碰到的那些 SDK 错误的原文、各自的含义，以及每个错误一步到位的修复方法，详见 **[故障排查](../troubleshooting.md)**。
