---
translation:
  sections: [09c857a25a9dc37a, 43bc6a76a243a50e, 0a716022a88768df, 4b7f78042bfcfff7, c112662e61b03315, 58974ba1f489a8b4, d18adbdbb835ea73]
  tool: 1
---
# 会话组 {#session-groups}

一个 `Client` 连接一个服务器。实际应用往往需要好几个（一个搜索服务器、一个数据库服务器、一个内部 API），结果要为每个服务器各管一条连接和一份工具列表。

**`ClientSessionGroup`** 是一个对象，它持有多条连接，并把它们公开的所有内容合并成一个统一视图。

## 两个服务器 {#two-servers}

先看两个普通的服务器。它们彼此毫无关联，所以很自然地都把自己的工具命名为 `search`：

```python title="library_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial001.py"
```

```python title="web_server.py" hl_lines="7"
--8<-- "docs_src/session_groups/tutorial002.py"
```

## 一个组 {#one-group}

创建一个 `ClientSessionGroup`，对每个服务器调用一次 **`connect_to_server`**：

```python title="client.py" hl_lines="10-12"
--8<-- "docs_src/session_groups/tutorial003.py"
```

* `connect_to_server` 接受的是传输参数，而不是服务器对象：用 `StdioServerParameters`（来自 `mcp`）启动子进程，或用 `StreamableHttpParameters` / `SseServerParameters`（来自 `mcp.client.session_group`）连接已在某个 URL 上监听的服务器。
* `group.tools` 是一个 `dict[str, Tool]`，包含所有已连接服务器的工具。`group.resources` 和 `group.prompts` 形式相同。
* `group.call_tool(name, arguments)` 查找名称，找到拥有它的会话，然后转发调用。不需要指明是哪个服务器。

!!! check
    把 `client.py` 放在两个服务器旁边运行。第二次 `connect_to_server` 会被拒绝：

    ```text
    mcp.shared.exceptions.MCPError: {'search'} already exist in group tools.
    ```

    这是一个 `MCPError`，在第二个服务器的任何内容注册之前就抛出了。名称必须在**整个**组内唯一，而两个不受你控制的服务器迟早会冲突。

## `component_name_hook` {#component_name_hook}

这个问题在组这一层解决，而不是在服务器上。传入一个接受 `(name, server_info)` 的函数，组会对它注册的每个名称都运行这个函数：

```python title="client.py" hl_lines="7-8 15"
--8<-- "docs_src/session_groups/tutorial004.py"
```

再运行一次。`print(sorted(group.tools))` 现在两个都显示了：

```text
['Library.search', 'Web.search']
```

* **键**由你决定。`by_server` 用 `server_info.name` 构造它，也就是每个 `MCPServer(...)` 构造时传入的名称。
* 里面的 `Tool` 原封不动：`group.tools["Web.search"].name` 仍然是 `"search"`，这也是 `call_tool` 发到线路上的名称。前缀永远不会离开你的进程。
* 不只是工具。library 的 `hours` 资源注册为 `Library.hours`。

!!! tip
    这个 hook 对**每个**服务器的**每个**名称都会运行，而不仅限于冲突的名称：没有"仅在冲突时加前缀"的模式。选定一种方案，让它处处生效。

## 添加和移除服务器 {#adding-and-removing-servers}

`connect_to_server` 返回它打开的 `ClientSession`。如果以后想移除这个服务器，就保留它：`await group.disconnect_from_server(session)` 会把它的工具、资源和提示词从组中移除。

如果手上已经有一个已连接的 `ClientSession`（`Client.session` 就是一个），把它交给 `await group.connect_with_session(server_info, session)`，而不用打开新的传输。聚合方式相同。组永远不会关闭不是它自己打开的会话。`server_info` 为组件前缀提供服务器名称；在 2026 年代的连接上，`client.server_info` 可能是 `None`（身份是可选的），这种情况下传入你自己的 `Implementation(name=..., version=...)`。

## 经典握手 {#the-classic-handshake}

`ClientSessionGroup` 构建在 `ClientSession` 之上，而不是 `Client`。每次 `connect_to_server` 都运行经典的 `initialize` 握手。它从不发送 **[协议版本](../protocol-versions.md)** 中描述的 `server/discover` 探测。每个 MCP 服务器都理解这种握手，所以这不会损失任何兼容性；它只意味着，面对一个本可以做得更好的服务器，组走的是较旧、较慢的路径。

## 回顾 {#recap}

* `ClientSessionGroup` 持有多条服务器连接，并把它们的工具、资源和提示词各自合并成一个 `dict`。
* 每个服务器调用一次 `connect_to_server(params)`。它接受传输参数，从不接受 `Client` 所接受的服务器对象或 URL。
* `group.call_tool(name, arguments)` 替你路由到拥有该工具的服务器。
* 名称必须在整个组内唯一；两个都有 `search` 工具的服务器无法直接共存。
* `component_name_hook=` 改写每个注册的名称。改变的是 dict 的键，线路上的名称不变。
* `connect_with_session` 添加一个你已持有的会话；`disconnect_from_server` 移除一个。

组所用的握手（以及 `Client` 更倾向的那种更快的握手）详见 **[协议版本](../protocol-versions.md)**。
