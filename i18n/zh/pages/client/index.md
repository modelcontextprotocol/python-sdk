---
translation:
  sections: [ebef1e7a0df854f4, a4c687d3d627d516, 8e79141fc2985342, b345dd05b9c3c7ab, 80ce41579825a6fa, 5f0fa90494de8f65, 83d10514eaa62fa5, 9190555aa39a5d28, 84a4c9d8bf14dddb, 927d71cf40b58c30]
  tool: 1
---
# Client {#the-client}

**`Client`** 是 Python 程序与 MCP 服务器对话的方式。

它是一个对象，只有一套生命周期：构造它，进入 `async with`，然后调用方法。每个协议动词（列出工具、调用工具、读取资源、渲染提示词）都是它上面的一个 `async` 方法，返回带类型的结果。

## 你的第一个客户端 {#your-first-client}

```python title="client.py" hl_lines="14-18"
--8<-- "docs_src/client/tutorial001.py"
```

顶部的服务器只是为了让你有东西可连。客户端就是高亮的那五行。

* `Client(mcp)` 接收的是**服务器对象本身**。这是内存传输：没有子进程，没有端口，没有 HTTP。本页的每个示例，以及你写的每个测试，都是这样连接的。
* `async with` 就是**生命周期**。进入时连接并协商；离开时断开。没有 `connect()` / `close()` 这样的配对方法，而且 `Client` 在代码块结束后不能复用。
* 在代码块内部，连接相关的信息已经作为普通属性摆在那里了。

### 可以传给 `Client` 什么 {#what-you-can-pass-to-client}

`Client` 接收一个位置参数，并根据它的类型确定传输方式：

* `MCPServer`（或低层 `Server`）实例：**进程内**连接。
* URL 字符串（`Client("http://localhost:8000/mcp")`）：Streamable HTTP，生产环境的路径。
* **传输**：任何可以 `async with ... as (read, write)` 的对象，比如包装子进程的 `stdio_client(...)`。

本页其余内容在这三种方式下完全相同。请求头、子进程、超时以及 `Transport` 协议另有专页：**[客户端传输](transports.md)**。

### 已连接的客户端上有什么 {#whats-on-a-connected-client}

四个只读属性，进入代码块的那一刻就已填好：

* `client.server_info`：服务器的身份信息；对于不报告身份的 2026 时代服务器则为 `None`（python-sdk 服务器默认会报告）。这里 `server_info.name` 是 `"Bookshop"`，`server_info.version` 是服务器报告的版本。
* `client.server_capabilities`：服务器能做什么（`tools`、`resources`、`prompts`、`completions`……）。服务器没有的能力是 `None`。
* `client.protocol_version`：双方商定的协议版本。这里是 `"2026-07-28"`。
* `client.instructions`：服务器的 `instructions=` 字符串，没设置则为 `None`。

你从没选过协议版本。默认情况下，`Client` 会探测服务器，遇到较老的服务器就回退到经典握手，所以一个客户端能对接任何时代的服务器。需要控制这一点时，详见 **[协议版本](../protocol-versions.md)**。

!!! tip
    `client.session` 是底层的 `ClientSession`，即低层的逃生出口。本页的任何内容都用不到它。

## 列出工具 {#listing-tools}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial002.py"
```

`list_tools()` 返回 `ListToolsResult`；工具在 `.tools` 里。每一个都是宿主会交给模型的完整定义：

```python
tool.name          # 'search_books'
tool.title         # 'Search the catalog'
tool.description   # 'Search the catalog by title or author.'
```

而 `tool.input_schema` 是服务器从函数类型注解推导出的 JSON Schema：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"},
    "limit": {"default": 10, "title": "Limit", "type": "integer"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

UI 渲染参数表单所需的一切，以及模型生成合法参数所需的一切，都在这个模式里。

!!! tip
    `title` 是可选的，所以把工具展示给人看的 UI 必须做选择：有 `title` 就用它，没有就用 `name`。`from mcp.shared.metadata_utils import get_display_name` 做的正是这件事，适用于工具、资源、资源模板和提示词。

## 调用工具 {#calling-a-tool}

`call_tool(name, arguments)` 运行工具，返回 `CallToolResult`。

```python title="client.py" hl_lines="26-33"
--8<-- "docs_src/client/tutorial003.py"
```

服务器的 `lookup_book` 返回一个 Pydantic `Book`。客户端看到的是这样的：

```python
result.content             # [TextContent(type='text', text='{\n  "title": "Dune",\n  "author": "Frank Herbert",\n  "year": 1965\n}')]
result.structured_content  # {'title': 'Dune', 'author': 'Frank Herbert', 'year': 1965}
result.is_error            # False
```

一个返回值，三样东西要读。各自有不同的使用者。

### `content`：模型读的内容 {#content-what-the-model-reads}

`content` 是一个**内容块**的 `list`，而内容块是一个联合类型：`TextContent`、`ImageContent`、`AudioContent`、`ResourceLink` 或 `EmbeddedResource`。一个工具可以返回多个不同种类的块。

这就是为什么 `main` 在碰 `block.text` 之前先用 `isinstance(block, TextContent)` 收窄类型。注意 `isinstance` 之外没有出现 `.text`：类型检查器不允许，因为 `ImageContent` 有的是 `.data`，不是 `.text`。这个联合类型如实表达了工具可以发给你什么；你的代码也应该如此。

### `structured_content`：应用程序读的内容 {#structured_content-what-your-application-reads}

`structured_content` 是工具返回值的 JSON 形式，符合工具声明的 `output_schema`。不用解析字符串，不用猜。

两者同时存在时，是有意把同一件事说两遍：`content` 给模型，`structured_content` 给代码。结构化这一半从哪里来、如何控制，见 **[结构化输出](../servers/structured-output.md)** 页面。

### `is_error`：工具是否失败 {#is_error-whether-the-tool-failed}

抛出异常的工具**不会**在客户端里抛出异常。它作为一个普通结果返回，带 `is_error=True`。

!!! check
    向 `lookup_book` 查询 `"Solaris"`（目录里没有的书名），函数会抛出 `ValueError`。调用仍然正常返回：

    ```python
    result.is_error            # True
    result.content             # [TextContent(type='text', text="Error executing tool lookup_book: No book titled 'Solaris' in the catalog.")]
    result.structured_content  # None
    ```

    异常消息落在了 `content` 里，**模型**可以读到它并重试。这是有意为之：工具错误是对话的一部分，不是崩溃。在相信 `structured_content` 之前，务必先看 `is_error`。

!!! warning
    `is_error=True` 涵盖的不只是你自己的 `raise`。请求一个服务器根本没有的工具（`call_tool("does_not_exist", {})`），什么异常都不会抛出。返回的形状相同：`is_error=True`，`content` 里是 `Unknown tool: does_not_exist`。只有当服务器回复的是 JSON-RPC **错误**而不是结果时，`Client` 方法才会抛出 `MCPError`；服务器在什么情况下产生哪一种，见 **[处理错误](../servers/handling-errors.md)**。

## 资源 {#resources}

资源动词成对出现：两种列出方式，一种读取方式。

```python title="client.py" hl_lines="22-31"
--8<-- "docs_src/client/tutorial004.py"
```

* `list_resources()` 返回**具体**资源，即 URI 固定的那些。这里是 `['catalog://genres']`。
* `list_resource_templates()` 返回**参数化**的资源。这里是 `['catalog://genres/{genre}']`。它们是两个不同的列表，因为模板在填好之前是不可读的。
* `read_resource(uri)` 接收一个普通的 `str` URI，对两者都适用：传入 `"catalog://genres/poetry"`，服务器会把它匹配到模板上。

`read_resource` 返回 `contents`，一个由 `TextResourceContents` 或 `BlobResourceContents` 组成的列表。思路和工具内容一样：用 `isinstance` 收窄，再读 `.text`（或 `.blob`）。

客户端还可以在资源变化时收到通知。在 2025 时代的连接上，这是 `subscribe_resource(uri)` / `unsubscribe_resource(uri)`——`MCPServer` 没有实现这对方法，所以在 2026-07-28 线路上（这些动词已不存在），请求会回复 `-32601`，即“Method not found”。2026 的替代方案是 `subscriptions/listen` 流，`MCPServer` **确实**提供它——那里 `server_capabilities.resources.subscribe` 为 `True`——用 `client.listen(...)` 消费它的方法见本节的 **[订阅](subscriptions.md)** 页面。

## 提示词 {#prompts}

```python title="client.py" hl_lines="15-20"
--8<-- "docs_src/client/tutorial005.py"
```

`list_prompts()` 告诉你服务器提供什么，以及每个提示词需要什么：

```python
prompt.name        # 'recommend'
prompt.title       # 'Recommend a book'
prompt.arguments   # [PromptArgument(name='genre', required=True)]
```

`get_prompt(name, arguments)` 渲染它。参数字典是 `str -> str`：提示词参数永远是字符串。结果是 `messages`，一个 `PromptMessage` 列表，每个带有 `role` 和一个 `content` 块：

```python
message.role     # 'user'
message.content  # TextContent(type='text', text='Recommend one poetry book from the catalog and say why.')
```

宿主把这些消息直接交给模型。整个功能就这些。

## 补全 {#completions}

带有补全处理函数的服务器可以在用户输入时自动补全提示词和资源模板的参数。

```python title="client.py" hl_lines="27-31"
--8<-- "docs_src/client/tutorial006.py"
```

* `ref` 指明正在填写**哪个**提示词或模板：`PromptReference` 或 `ResourceTemplateReference`。
* `argument` 是 `{"name": ..., "value": ...}`：参数名以及用户目前输入的内容。

答案在 `result.completion.values` 里。输入 `"p"`，服务器返回 `['poetry']`。服务器端的写法，以及处理函数如何利用**其他**已填好的参数来缩小建议范围，见 **[补全](../servers/completions.md)** 页面。

## 分页 {#pagination}

每个 `list_*` 方法都接收 `cursor=` 关键字参数，每个结果都带 `next_cursor`。`next_cursor` 为 `None` 时，说明已经拿全了。

```python title="client.py" hl_lines="22-30"
--8<-- "docs_src/client/tutorial007.py"
```

这个循环对任何服务器都正确。`MCPServer` 一页返回全部内容，所以 `next_cursor` 是 `None`，循环只跑一次，这也是为什么大多数代码从来不写它。真正分页的服务器，以及游标遵守的规则，见 **[分页](../advanced/pagination.md)**。

## 在测试中 {#in-tests}

没有进程、没有端口的 `Client(mcp)`，本身就是服务器的测试工具。

有一个构造参数专为此而设：`Client(mcp, raise_exceptions=True)`。它只对内存连接生效，**[测试](../get-started/testing.md)** 页面会解释它，并围绕它搭建完整的模式。

## 回顾 {#recap}

* `Client(x)` 传入服务器对象时走内存连接，传入 URL 字符串时走 Streamable HTTP，其他情况通过传输连接。
* `async with` 就是全部生命周期。在它内部，`server_capabilities` 和 `protocol_version` 已经填好；服务器提供时，`server_info` 和 `instructions` 也已填好。
* `list_tools()` 给出每个工具的 `name`、`title`、`description` 和 `input_schema`。
* `call_tool()` 返回给模型的 `content`、给代码的 `structured_content`，以及 `is_error`。抛异常的工具是一个结果，不是异常。
* `content` 是块类型的联合；读取前先用 `isinstance` 收窄。
* `list_resources` / `list_resource_templates` / `read_resource`、`list_prompts` / `get_prompt` 和 `complete` 补齐了全部动词。
* 每个 `list_*` 都接收 `cursor=`；循环到 `next_cursor` 为 `None` 为止。

服务器可以向**客户端**请求什么，以及你如何回应，见 **[客户端回调](callbacks.md)**。
