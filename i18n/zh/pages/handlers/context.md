---
translation:
  sections: [b50152f05c81e786, b302059b22fb7cb4, 85682a1bf561243a, 53fc48838eb6837a, b24190e0842786ec, 85f93e150fc9b240]
  tool: 1
---
# Context {#the-context}

工具的参数来自模型。其余的一切（正在处理的请求、所在的服务器、与客户端对话的途径）都来自同一个对象：**`Context`**。

你不需要构造它，也不需要配置它。只需要声明它。

## 声明它 {#ask-for-it}

给任意工具加一个用 `Context` 标注的参数：

```python title="server.py" hl_lines="2 8"
--8<-- "docs_src/context/tutorial001.py"
```

* SDK 为每个请求构建一个新的 `Context` 并传进来。
* 参数**名字无关紧要**。`ctx`、`context`、`c` 都行：SDK 靠注解找到它。
* 资源和提示词也可以用同样的方式声明一个。
* `ctx.request_id` 是函数当前正在处理的请求的 id。

!!! info
    如果用过 FastAPI，这一招应该不陌生：用框架自己的类型声明一个参数（那边是 `Request`，这边是 `Context`），框架就会把它传进来。不需要注册，不需要配置：类型注解就是全部机制。

### 对模型不可见 {#invisible-to-the-model}

这一点要牢记。下面是 `tools/list` 为 `search_books` 报告的输入模式：

```json
{
  "type": "object",
  "properties": {
    "query": {"title": "Query", "type": "string"}
  },
  "required": ["query"],
  "title": "search_booksArguments"
}
```

只有一个属性。`ctx` 不是参数：它从不出现在模式里，模型从不会得知它的存在，也没有客户端能填写它。这是你和 SDK 之间的约定，在线路上不可见。

### 试一试 {#try-it}

用 MCP Inspector 运行服务器：

```console
uv run mcp dev server.py
```

`search_books` 的表单只有一个 `query` 字段。用 `dune` 调用它：

```text
[request 3] Found 3 books matching 'dune'.
```

这个数字就是这次请求碰巧的编号。再调用一次工具，它就会变：每个请求都有自己的 `Context`。

## 它提供什么 {#what-it-gives-you}

注入的对象很小。除了 `request_id`：

* `await ctx.read_resource(uri)`：在工具内部读取服务器**自己的**资源。见下一节。
* `await ctx.report_progress(progress, total, message)`：在长时间调用期间把进度流式发回调用方。详见 **[进度](progress.md)**。
* `await ctx.elicit(message, schema)` 和 `await ctx.elicit_url(...)`：暂停工具，向用户提一个问题。这是 **[征询](elicitation.md)**。
* `ctx.session`：服务器与这个客户端对话的这一端。发给客户端的通知都在这里；最后一节会用到它。
* `ctx.headers`：传输携带的请求头，stdio 上为 `None`。用 `(ctx.headers or {}).get("x-...")` 读取自定义请求头。请求头是客户端提供的输入——用来传语言区域或功能开关没问题，但绝不能用作身份。
* `ctx.request_context`：原始的每请求记录。你会用到的字段是 `lifespan_context`，也就是启动代码 yield 出来的对象（见 **[生命周期](lifespan.md)**）。

日志有意不在这个列表里。服务器用 Python 的 `logging` 模块记录日志，和任何其他 Python 程序一样。**[日志](logging.md)** 这一页简短地解释了原因。

!!! tip
    注入只发生在你注册的那个函数上。工具调用的辅助函数不会得到自己的 `Context`；把 `ctx` 当作普通参数传下去。不存在可以从别处获取的环境“当前上下文”。

## 读取自己的资源 {#read-your-own-resources}

服务器的资源不只是给客户端用的。工具也可以读取它们：

```python title="server.py" hl_lines="16"
--8<-- "docs_src/context/tutorial002.py"
```

`ctx.read_resource` 通过为 `resources/read` 提供服务的同一个注册表解析 URI，所以工具拿到的和客户端拿到的一样：一个 `ReadResourceContents` 的可迭代对象，每个内容块一个。这个 URI 只有一个：

```python
contents.content    # 'fiction, non-fiction, poetry'
contents.mime_type  # 'text/plain'
```

* `content` 正是 `genres()` 返回的内容。单一事实来源：客户端浏览资源，你的工具消费它，没人复制字符串。
* `describe_catalog` 唯一的参数是 `Context`，所以它的输入模式**完全没有属性**。模型用 `{}` 调用它。

## 告诉客户端列表变了 {#tell-the-client-the-list-changed}

服务器提供的内容并不是在导入时就固定的。在运行时注册一个工具，然后告诉客户端：

```python title="server.py" hl_lines="15-16"
--8<-- "docs_src/context/tutorial003.py"
```

* `mcp.add_tool(recommend_book)` 把一个普通函数注册为工具：名称、描述和模式的推导方式与 `@mcp.tool()` 完全一致。
* `await ctx.session.send_tool_list_changed()` 发送 `notifications/tools/list_changed`。收到它的客户端会再次调用 `tools/list`，并看到 `recommend_book`。

同类方法还有 `send_resource_list_changed()`、`send_prompt_list_changed()`，以及针对某个特定资源变化的 `send_resource_updated(uri)`。

在 2026-07-28 连接上，客户端只在自己打开的 `subscriptions/listen` 流上接收变更通知，所以上面的 `send_*` 方法到不了这些流。`Context` 的发布方法会一次性投递到所有已订阅的流：`await ctx.notify_tools_changed()`、`await ctx.notify_prompts_changed()`、`await ctx.notify_resources_changed()` 和 `await ctx.notify_resource_updated(uri)`。完整说明，包括跨副本横向扩展，详见 **[订阅](subscriptions.md)**。

!!! check
    在有人运行 `enable_recommendations` 之前，你承诺的那个工具并不存在。照样调用它，结果是一条模型能读懂的错误：

    ```text
    Unknown tool: recommend_book
    ```

    运行 `enable_recommendations`，同样的调用就会成功。工具列表是真正动态的：`tools/list` 反映的是**此刻**注册了什么。

## 回顾 {#recap}

* 用 `Context` 标注一个参数（在工具、资源或提示词里），SDK 就会注入它。名字随你定。
* 它对模型不可见：输入模式永远只包含你真正的参数。
* `ctx.request_id` 标识请求；`ctx.request_context.lifespan_context` 是启动代码 yield 出来的对象。
* `await ctx.read_resource(uri)` 让工具读取服务器自己的资源。
* `ctx.session` 是回到客户端的通道：`send_tool_list_changed()` 及其同类方法告诉客户端重新获取你改动过的列表。
* 进度报告和征询同样从 `Context` 开始；它们各有自己的页面。

模型永远看不到、由你自己的函数填充的参数，就是 **[依赖](dependencies.md)**。
