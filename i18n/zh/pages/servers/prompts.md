---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, d30d3c20168b88b2, f5ef38dad59d6f76, 6e38a699ba57fbdf, 2b984a3bf37a0ddd]
  tool: 1
---
# 提示词 {#prompts}

**提示词**是由用户挑选的消息模板。

工具是给模型用的。提示词正好相反：用户在客户端的菜单里（比如斜杠命令或按钮）选一个，填好参数，渲染出来的消息就进入对话，就像是用户自己打出来的一样。

在一个返回文本的函数上加 `@mcp.prompt()`，就声明了一个提示词。

## 第一个提示词 {#your-first-prompt}

```python title="server.py" hl_lines="6-9"
--8<-- "docs_src/prompts/tutorial001.py"
```

SDK 从中读取的三样东西和工具一样：

* **名称**就是函数名：`review_code`。
* 客户端显示的**描述**是 docstring：`Review a piece of code.`
* **参数**来自函数的形参。`code` 没有默认值，所以是必填的。

客户端从 `prompts/list` 拿到的就是这些：

```json
{
  "name": "review_code",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "required": true}
  ]
}
```

这里没有 JSON Schema。提示词的参数是一个扁平的**具名字符串值**列表：是给人填的表单，而不是由模型构造的载荷。

### 渲染 {#rendering-it}

客户端用 `prompts/get` 渲染模板，并传入参数。你的函数运行后，返回的 `str` 会变成**一条用户消息**：

```json
{
  "description": "Review a piece of code.",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this code:\n\ndef add(a, b): return a + b"
      }
    }
  ],
  "resultType": "complete"
}
```

提示词的完整流程就是这样：按名称列出，按需渲染，放进对话。

!!! check
    `required` 的检查发生在你的函数运行之前。渲染 `review_code` 时不传 `code`，请求本身就会失败，并返回一个 JSON-RPC 错误（错误码 `-32603`）：

    ```text
    mcp.shared.exceptions.MCPError: Internal server error
    ```

    这里没有工具那种可以交回给模型的错误结果，因为整个环节里根本没有模型：调用会直接抛出异常。原因（`Missing required arguments: {'code'}`）会记在服务器的日志里。

### 试一试 {#try-it}

用 MCP Inspector 运行服务器：

```console
uv run mcp dev server.py
```

打开 **Prompts** 标签页，选择 `review_code`。Inspector 会画出一个表单，带一个必填的 `code` 字段。填好、渲染，返回的正是上面那条用户消息。

## 不止一条消息 {#more-than-one-message}

代码审查只要一条消息。调试则是一段对话，而提示词可以把整段对话的开头都铺好。

把返回值从 `str` 换成消息列表：

```python title="server.py" hl_lines="2 13-20"
--8<-- "docs_src/prompts/tutorial002.py"
```

* `UserMessage` 和 `AssistantMessage` 来自 `mcp.server.mcpserver.prompts.base`。给它们一个 `str`，它们会替你包装成 `TextContent`。角色由类名决定。
* `Message` 是它们的公共基类。用它作返回值注解。

现在渲染 `debug_error` 会按顺序产生三条消息：

```json
{
  "description": "Start a debugging conversation.",
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "I'm seeing this error:"}},
    {"role": "user", "content": {"type": "text", "text": "TypeError: 'int' object is not iterable"}},
    {
      "role": "assistant",
      "content": {"type": "text", "text": "I'll help debug that. What have you tried so far?"}
    }
  ],
  "resultType": "complete"
}
```

注意最后一条。预先填入一轮 `assistant` 发言，就能引导模型的**下一条**回复，而不用让用户自己把引导的话敲出来。

## 标题和参数描述 {#titles-and-argument-descriptions}

`review_code` 是函数名，不是标签。给客户端一个更适合放在按钮上的名字，并给每个参数加上描述，让表单一目了然：

```python title="server.py" hl_lines="10-13"
--8<-- "docs_src/prompts/tutorial003.py"
```

* `title="Code review"` 是给人看的名称，和工具的 `title` 一模一样。
* `Annotated[str, Field(description=...)]` 和 **[工具](tools.md)** 用来描述工具参数的是同一种写法。这里描述直接落在参数上，而不是写进模式里。
* `language` 有默认值，所以不再是必填参数。

现在 `prompts/list` 里的这一项包含了客户端画好一个表单所需的全部信息：

```json
{
  "name": "review_code",
  "title": "Code review",
  "description": "Review a piece of code.",
  "arguments": [
    {"name": "code", "description": "The code to review.", "required": true},
    {"name": "language", "description": "The language the code is written in.", "required": false}
  ]
}
```

!!! info
    如果读过 **[工具](tools.md)**，到这里为止的内容你其实都已经会了。装饰器一样，用 docstring 作描述一样，`Annotated`/`Field` 也一样。变的只有两点：由谁触发（用户），以及结果去哪儿（进入对话）。

## 不止文本 {#more-than-text}

`UserMessage` 和 `AssistantMessage` 在接受 `str` 的地方，也接受内容块，或者 `Image` / `Audio` 辅助类。提示词里常见两种情况：附上一份文档，和附上一张图片。

### 嵌入文件 {#embedding-a-file}

```python title="server.py" hl_lines="5 12 21 23"
--8<-- "docs_src/prompts/tutorial004.py"
```

* 风格指南是位于 `style://python` 的资源（**[资源](resources.md)** 会介绍这类东西），从 `server.py` 旁边的 `style-guide.md` 读取。在那里放任意一个 Markdown 文件即可。
* `EmbeddedResource(resource=TextResourceContents(...))` 两者都来自 `mcp.types`，它把文件连同 URI 和 MIME 类型一起作为第一条消息携带；引用它的请求以纯文本形式跟在后面。
* 用嵌入，而不是把指南直接贴进 f-string，客户端就能把它显示为附件，之后还能重新打开 `style://python`，模型收到的也是原封不动的文件。二进制文件用 `BlobResourceContents`，带一个 base64 的 `blob`。

渲染后，第一条消息的 `content` 是一个 `resource` 块：

```json
{"type": "resource", "resource": {"uri": "style://python", "mimeType": "text/markdown", "text": "* Prefer early returns.\n..."}}
```

### 附上图片 {#attaching-an-image}

```python title="server.py" hl_lines="4 15"
--8<-- "docs_src/prompts/tutorial005.py"
```

* `Image` 是 **[图片、音频和图标](media.md)** 里的辅助类。提示词渲染时，`UserMessage` 把它转换成一个 `ImageContent` 块（文件经 base64 编码，MIME 类型从 `.png` 推断）；`Audio` 同样会变成 `AudioContent`。
* 在 `server.py` 旁边放任意一个名为 `architecture.png` 的 PNG。提示词参数都是字符串，所以图片总是来自服务器；`component` 只提供文字。

```json
{"type": "image", "data": "iVBORw0KGgoAAAANSUhEUg...", "mimeType": "image/png"}
```

## 在运行时修改列表 {#changing-the-list-at-runtime}

客户端连接期间也可以添加提示词，比如让用户把一条指令保存成自己的菜单项。先注册提示词，再发通知：

```python title="server.py" hl_lines="5 23-27"
--8<-- "docs_src/prompts/tutorial006.py"
```

* `mcp.add_prompt(Prompt.from_function(fn, name=..., description=...))` 注册函数的方式和 `@mcp.prompt()` 完全一样，`mcp.remove_prompt(name)` 则相反。`add_prompt` 遇到同名的现有条目会保留它而不是覆盖，所以这个工具先删掉旧条目，让保存变成替换。`prompts/list` 立即反映这一变化。
* `await ctx.notify_prompts_changed()` 向每个在 `subscriptions/listen` 流上监听的 `2026-07-28` 客户端发送 `notifications/prompts/list_changed`（**[订阅](../handlers/subscriptions.md)**）。当发起调用的客户端是 2026 之前的版本时，`await ctx.session.send_prompt_list_changed()` 把它发给这个客户端（**[服务旧版客户端](../run/legacy-clients.md)**）。两个都调用；没有人可通知时，它们各自什么也不做。
* 收到通知的客户端会再次调用 `prompts/list`。在 Python `Client` 里就是 `async with client.listen(prompts_list_changed=True) as sub:`，它会产出一个 `PromptsListChanged` 事件。

## 回顾 {#recap}

* 在函数上加 `@mcp.prompt()`，它就成了提示词。名称取自函数名，描述取自 docstring。
* 提示词由**用户控制**：客户端列出它们，用户选一个并填好参数。
* 参数是一个扁平的具名字符串列表（没有模式）。有默认值的形参是可选的。
* 返回 `str`，它就变成一条用户消息。返回 `UserMessage` / `AssistantMessage` 的列表，可以为多轮对话铺好开头。
* `title=` 和 `Field(description=...)` 是客户端放进 UI 里的内容。
* 缺少必填参数会让整个请求失败。没有针对单个提示词的错误结果。
* 把 `EmbeddedResource` 或 `Image` 包进 `UserMessage`，就能附上文档或图片。
* 运行时用 `mcp.add_prompt(...)` / `mcp.remove_prompt(...)` 添加或移除提示词，然后 `await ctx.notify_prompts_changed()` 和 `await ctx.session.send_prompt_list_changed()`。

要在服务器端为提示词（或资源模板）的参数提供自动补全，见 **[补全](completions.md)**。
