---
translation:
  sections: [81862a209b483d27, b76e8073487afa03, bc214b2fc2bcdae4, d5835477c0b60163, a5d9786f902ad8e1]
  tool: 1
---
# 请求头参数 {#header-parameters}

大多数服务器都用不到这个。

服务器前面的网关或负载均衡器只能根据不解析请求体就能读到的内容来路由。用 `x-mcp-header` 标记一个工具参数，使用 `2026-07-28` **[协议版本](../protocol-versions.md)** 的客户端就会把它的值同时作为 HTTP 请求头发送。

## 标记参数 {#mark-an-argument}

这个标记就是参数的 JSON Schema 里多出的一个键。在 `MCPServer` 上，由 `Field` 把它放进去：

```python title="server.py" hl_lines="13"
--8<-- "docs_src/header_parameters/tutorial001.py"
```

* 在 `2026-07-28` 的 Streamable HTTP 上，客户端会在请求体之外同时发送 `Mcp-Param-Region`。两者不一致时，服务器会拒绝这次调用。
* 没有列出过该工具的客户端从未见过这个标记：它不会发送请求头，调用会遭到拒绝。这时本 SDK 的 `Client` 会列出工具并重发一次调用，所以先列出工具只是省去一次往返。
* 其他所有连接都会忽略这个注解。

函数不用改：`region` 仍然作为参数传入。

## 哪些参数可以标记 {#what-can-be-marked}

`str`、`int` 和 `bool` 类型的参数。其他类型在注册工具时都会被拒绝，并抛出 `InvalidSignature`。

这也包括 `str | None`，因为它没有单一的类型。可选参数需要用 Pydantic 的 `WithJsonSchema` 把模式明确写出来：

```python
region: Annotated[str | None, WithJsonSchema({"type": "string", "x-mcp-header": "Region"})] = None
```

## 在底层 `Server` 上 {#on-the-low-level-server}

在那里 `input_schema` 是手写的，所以直接把这个键写进去：

```python title="server.py" hl_lines="18"
--8<-- "docs_src/header_parameters/tutorial002.py"
```

* 没有任何东西替你检查这个注解：无效的注解会照样提供出去，`2026-07-28` 客户端则会把这个工具从列表中剔除。

### 按名称获取模式 {#schemas-by-name}

要检查请求头，SDK 需要在分发调用之前拿到工具的输入模式。没有 `get_tool_input_schema` 时，每次调用只要带有参数，SDK 就会运行你的 `on_list_tools` 处理函数来获取它，不管有没有工具被标记。

```python title="server.py" hl_lines="26 39-41 48"
--8<-- "docs_src/header_parameters/tutorial003.py"
```

* 传入这个函数，就能直接用你手头已有的数据来回答。
* 对于没有需要检查内容的工具，返回 `None`。

## 回顾 {#recap}

* 给工具参数加上 `x-mcp-header`，`2026-07-28` 客户端就会把它再作为 `Mcp-Param-*` HTTP 请求头发送一遍。
* 请求头与请求体不一致的调用，服务器会拒绝。
* 只有 `str`、`int` 和 `bool` 参数可以标记。遇到其他类型，`MCPServer` 会抛出 `InvalidSignature`。
* 底层 `Server` 什么都不检查，而客户端会丢弃注解无效的工具。
* `get_tool_input_schema` 让底层 `Server` 不必在每次调用时都运行 `on_list_tools`。

手写 `Server` API 的其余内容见 **[底层 Server](low-level-server.md)**。
