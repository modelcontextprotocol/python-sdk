---
translation:
  sections: [d65c098f37f5b6c3, dd0c2724d6f2877e, 6835bb3570c6714c, ffe823cb0fedd488, f33651add1b59094]
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
    如果读过 **[工具](tools.md)**，这一页的内容你其实都已经会了。装饰器一样，用 docstring 作描述一样，`Annotated`/`Field` 也一样。变的只有两点：由谁触发（用户），以及结果去哪儿（进入对话）。

## 回顾 {#recap}

* 在函数上加 `@mcp.prompt()`，它就成了提示词。名称取自函数名，描述取自 docstring。
* 提示词由**用户控制**：客户端列出它们，用户选一个并填好参数。
* 参数是一个扁平的具名字符串列表（没有模式）。有默认值的形参是可选的。
* 返回 `str`，它就变成一条用户消息。返回 `UserMessage` / `AssistantMessage` 的列表，可以为多轮对话铺好开头。
* `title=` 和 `Field(description=...)` 是客户端放进 UI 里的内容。
* 缺少必填参数会让整个请求失败。没有针对单个提示词的错误结果。

要在服务器端为提示词（或资源模板）的参数提供自动补全，见 **[补全](completions.md)**。
