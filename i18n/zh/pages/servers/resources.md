---
translation:
  sections: [09df998c2a799f78, 0cf131146d16d4f9, 4e6b91e3f8025346, 8fe4eef576db17ed, 0d0d1ed43e3d0a53]
  tool: 1
---
# 资源 {#resources}

**资源**是你暴露出来、供应用程序读取的数据。

区别就在这里。工具是由**模型**决定调用的东西。资源是由**应用程序**决定加载的东西（一个配置文件、一条记录、一份文档），加载后作为上下文放到模型面前。

在一个普通的 Python 函数上加 `@mcp.resource(uri)`，就声明了一个资源。

## 第一个资源 {#your-first-resource}

```python title="server.py" hl_lines="6-8"
--8<-- "docs_src/resources/tutorial001.py"
```

形式和工具一样，只多了一样东西：**URI**。资源靠地址定位，而不是靠名称。客户端请求的是 `config://app`，从来不是 `get_config`。

其余信息，SDK 照样从函数里读取：

* **名称**是函数名：`get_config`。
* 客户端看到的**描述**是 docstring。
* **内容**就是你返回的东西。

`resources/list` 期间，客户端拿到的是：

```json
{
  "name": "get_config",
  "uri": "config://app",
  "description": "The active shop configuration.",
  "mimeType": "text/plain"
}
```

当它读取 `config://app` 时，你的函数运行，返回值以文本形式返回：

```python
result.contents  # [TextResourceContents(uri="config://app", mime_type="text/plain", text="theme=dark\nlanguage=en")]
```

!!! tip
    列出资源的开销很小。`resources/list` 期间**不会**调用你的函数，只在 `resources/read` 期间调用，而且只针对被请求的那个 URI。哪怕暴露一千个资源，也只为有人打开的那些付出开销。

### 试一试 {#try-it}

用 MCP Inspector 运行服务器：

```console
uv run mcp dev server.py
```

打开它打印出来的 URL，进入 **Resources** 标签页。`config://app` 连同它的描述就在列表里。点一下，Inspector 就会读取它：你的两行配置就出来了。

## 资源模板 {#resource-templates}

每条记录一个 URI，这种做法扩展不了。在 URI 里放一个**占位符**，再给函数加一个对应的参数：

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/resources/tutorial002.py"
```

URI 里写 `{user_id}`，函数上写 `user_id: str`。整个约定就这些。

它现在是一个**资源模板**，位置也变了：它离开 `resources/list`，改为出现在 `resources/templates/list` 里，不再是一个地址，而是一个模式：

```json
{
  "name": "get_user_profile",
  "uriTemplate": "users://{user_id}/profile",
  "description": "A customer's profile.",
  "mimeType": "text/plain"
}
```

客户端填上占位符，读取一个具体的 URI：`users://42/profile`、`users://ada/profile`。所有这些都由同一个函数应答，匹配到的值作为 `user_id` 传入：

```python
result.contents  # [TextResourceContents(uri="users://42/profile", text="User 42: 12 orders since 2021.")]
```

注意结果里的 `uri`。它是客户端请求的那个**具体** URI，不是模板。

!!! check
    占位符和参数必须对得上。把函数参数改名为 `user`，而 URI 里仍写着 `{user_id}`，装饰器就会在**导入时**拒绝，那时还没有任何客户端接触到它：

    ```text
    ValueError: Mismatch between URI parameters {'user_id'} and function parameters {'user'}
    ```

    不匹配只可能是 bug，所以 SDK 让带着这种不匹配的服务器根本无法启动。

占位符语法是 [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)：`{+path}` 表示跨多个分段的值，`{?q,lang}` 表示可选的查询参数，等等。SDK 默认还会对提取出的值做路径安全检查。完整参考见 **[URI 模板与路径安全](uri-templates.md)**。

`get_user_profile` 还可以接收一个注解为 `Context` 的参数。SDK 会把它注入进来，而绝不会把它当成 URI 参数；它能给你什么，见 **[Context](../handlers/context.md)** 页面。

## 返回什么 {#what-you-return}

不只限于 `str`。给每个资源一个 `mime_type`，返回合适的内容即可：

```python title="server.py" hl_lines="8-9 14-15 20-21"
--8<-- "docs_src/resources/tutorial003.py"
```

* `readme` 返回 `str`，因此原样发送。这是最常见的情况。
* `catalog_stats` 返回 `dict`，因此 SDK 替你把它序列化成 **JSON 文本**：

    ```json
    {
      "books": 1204,
      "authors": 391
    }
    ```

* `placeholder_cover` 返回 `bytes`，因此客户端拿到的是 `BlobResourceContents` 而不是 `TextResourceContents`，你的字节经 base64 编码后放在它的 `blob` 字段里。

同样的规则适用于其他任何可 JSON 序列化的东西：列表、Pydantic 模型、dataclass。只要既不是 `str` 也不是 `bytes`，就变成 JSON。

`mime_type` 由你来声明，默认是 `text/plain`。SDK 从不检查你返回的内容去猜它，所以一个没标注的 `dict` 资源仍然会以纯文本的类型对外宣告。

!!! tip
    不想从函数推导时，`@mcp.resource()` 也接受 `name=`、`title=` 和 `description=`。而当根本没有函数可写时，`mcp.server.mcpserver.resources` 里有现成的 `Resource` 类（`TextResource`、`BinaryResource`、`FileResource`、`HttpResource`、`DirectoryResource`），用 `mcp.add_resource(...)` 注册即可。

客户端还可以**订阅**一个资源，在它变化时收到通知；那是客户端那一半的事，详见 **[客户端](../client/index.md)**。

## 回顾 {#recap}

* 在函数上加 `@mcp.resource(uri)`，它就成了资源。URI 是地址，返回值是内容，docstring 是描述。
* URI 里有 `{placeholder}`，它就成了**模板**：列在 `resources/templates/list` 下，一个函数服务所有匹配的 URI。
* 占位符名必须和函数的参数名一致。写错了，导入时就会发现，而不是等到生产环境。
* 你的函数在资源被**读取**时运行，而不是在列出时。
* `str` 变成文本，`bytes` 变成 base64 blob，其他一切变成 JSON 文本。用 `mime_type=` 给它标注类型。
* 工具供模型采取行动。资源供应用程序读取。

第三种原语，也就是由人从菜单里挑选的那一种，是 **[提示词](prompts.md)**。
