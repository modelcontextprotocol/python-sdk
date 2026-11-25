---
translation:
  sections: [72f9c964769076dd, 9a2c14e10935b515, 235299eb78ab12d7, 8aee1e78c8237fb8, 9bd86acd4112138f, 55343cb7f250dc7b]
  tool: 1
---
# 补全 {#completions}

在你的服务器之上构建 UI 的客户端，会想在用户输入时自动补全参数值：语言名称、仓库名称、文件路径。

**补全**（completion）就是服务器提供这些建议的方式。

## 值得补全的东西 {#something-worth-completing}

补全只适用于两样东西：**提示词**的参数和**资源模板**的参数。所以先写一个两者各有一个的服务器：

```python title="server.py" hl_lines="6 12"
--8<-- "docs_src/completions/tutorial001.py"
```

这里还没有任何与补全相关的内容。

* `review_code` 接受一个 `language`。用户不该靠猜来知道你接受哪些写法。
* `github_repo` 接受 `owner` 和 `repo`。两个都用自由文本框，这个表单会很难用。

## 补全处理函数 {#the-completion-handler}

添加**一个**用 `@mcp.completion()` 装饰的函数：

```python title="server.py" hl_lines="21-29"
--8<-- "docs_src/completions/tutorial002.py"
```

* 每个服务器只有一个处理函数。所有补全请求都会落到这里，由你根据正在补全的对象分支处理。
* 它必须是 `async def`：SDK 会 await 它。
* 它接收三个参数：
  * `ref`：是**哪一个**提示词或资源模板，类型为 `PromptReference` 或 `ResourceTemplateReference`。用 `isinstance` 区分两者。
  * `argument`：`argument.name` 是正在补全的参数，`argument.value` 是用户目前已输入的内容。
  * `context`：已经确定的参数。暂时忽略它。
* 返回一个 `Completion(values=[...])`；没有可提供的建议时返回 `None`。

!!! tip
    `argument.value` 是用户已输入的前缀。SDK **不会**替你过滤：放进 `values` 的是什么，UI 显示的就是什么。`startswith` 得你自己写。

### 试一试 {#try-it}

用 **[测试](../get-started/testing.md)** 中的内存 `Client` 来驱动它。调用 `client.complete()`，传入 `ref=PromptReference(name="review_code")` 和 `argument={"name": "language", "value": "py"}`：

```python
result.completion.values  # ['python']
```

* `ref` 与处理函数收到的引用类型相同。
* `argument` 是一个普通的 dict，只有 `name` 和 `value` 两个键。

发送空的 `value`，会拿回整个列表。`lang.startswith("")` 对每种语言都为真：

```python
result.completion.values  # ['go', 'javascript', 'python', 'rust', 'typescript']
```

询问 `code`（一个处理函数不认识的参数），它会返回 `None`，SDK 会把它变成空列表：

```python
result.completion.values  # []
```

`None` 表示“没有建议”，绝不是错误。UI 会退回到普通的文本框。

## 一项你从未声明过的能力 {#a-capability-you-never-declared}

注册处理函数本身就是声明。连接一个客户端看看：

```python
client.server_capabilities.completions  # CompletionsCapability()
```

你没有在任何地方列出 `completions`。SDK 看到处理函数，就替你声明了这项能力。每一项**可选**能力都是这样：处理函数就是声明。（三种原语不是可选的：无论有没有处理函数，`MCPServer` 总会声明它们。）

!!! check
    回到第一个 `server.py`（没有处理函数的那个），照样向它发请求。调用会失败，并返回一个 JSON-RPC 错误：

    ```text
    Method not found
    ```

    而且 `client.server_capabilities.completions` 是 `None`。这正是能力的意义所在：行为规范的客户端会先检查它，绝不会发出你无法响应的请求。

## 有依赖关系的参数 {#dependent-arguments}

`github://repos/{owner}/{repo}` 有两个参数，而 `repo` 的有用取值取决于先选了哪个 `owner`。

这就是 `context` 的用处。它携带用户**已经确定**的参数：

```python title="server.py" hl_lines="8-11 34-38"
--8<-- "docs_src/completions/tutorial003.py"
```

* 新分支针对模板的 `repo` 参数触发。
* `context.arguments` 是 `dict[str, str] | None`，保存目前已选定的值（这里是 `owner`）。
* 还没有 `owner`，就没有合理的建议可给，所以处理函数返回 `None`。

客户端通过 `context_arguments=` 发送这些已确定的值。这次 `ref` 是 `ResourceTemplateReference(uri="github://repos/{owner}/{repo}")`。用空的 `value` 请求补全 `repo`，并传入 `context_arguments={"owner": "modelcontextprotocol"}`：

```python
result.completion.values  # ['python-sdk', 'typescript-sdk', 'inspector']
```

去掉 `context_arguments=`，同样的调用会返回 `[]`。不知道 owner，处理函数就无从知道该提供哪些仓库。

!!! info
    `Completion` 还接受 `total=` 和 `has_more=`。当 `values` 只是更长列表中的一段时设置它们，这样 UI 就能显示“另有 200 项”。大多数处理函数用不到它们。

## 回顾 {#recap}

* 补全是针对**提示词参数**和**资源模板参数**的建议。仅此而已。
* `@mcp.completion()` 注册这唯一的处理函数。它的形式是 `async def (ref, argument, context) -> Completion | None`。
* 根据 `isinstance(ref, ...)` 和 `argument.name` 分支。按 `argument.value` 过滤要自己写。
* `None` 会变成空列表。它绝不是错误。
* `context.arguments` 保存已确定的值；客户端通过 `context_arguments=` 提供它们。
* 一注册处理函数，`completions` 能力就会出现。没有它，请求的结果就是 `Method not found`。

建议在用户还在**填写**提示词或模板时有用；想在工具调用**中途**向用户提问，需要的是 **[征询（elicitation）](../handlers/elicitation.md)**。工具除了文本还能返回什么，见 **[图像、音频和图标](media.md)**。
