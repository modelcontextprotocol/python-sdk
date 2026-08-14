---
translation:
  sections: [fea8d769ff9edeba, ce8e2ad42f29ef71, 0d705efb19cf99c2, 7a53ead3e704a7f0, 9adc400e8c88e854, 318893ad8e2e9924, 6b63ab96b34476c0]
  tool: 1
---
# 运行服务器 {#running-your-server}

`mcp.run()` 启动服务器。

唯一需要做的决定是**传输方式**：服务器和客户端之间的字节究竟如何流动。

## 选择传输方式 {#pick-a-transport}

| 传输方式 | 是什么 | 何时使用 |
|---|---|---|
| `stdio` | 宿主把你的文件作为子进程启动，通过它的 stdin 和 stdout 通信。 | 本地服务器。默认值。 |
| `streamable-http` | 真正的 HTTP 服务器，监听一个端口。 | 任何要部署的东西。 |
| `sse` | 较旧的 HTTP 传输方式。 | 不要用。 |

!!! warning
    SSE 在 2025-03-26 协议修订版中已被 Streamable HTTP 取代。`mcp.run(transport="sse")` 仍然可用，也有自己的 `sse_path=` 和 `message_path=` 选项，但它只是为还没迁移的客户端留着的。不要在它之上构建任何新东西。

## `mcp.run()` {#mcprun}

```python title="server.py" hl_lines="12-13"
--8<-- "docs_src/run/tutorial001.py"
```

* `run()` 是同步的。服务器存活多久，它就阻塞多久。
* 不带参数时，传输方式是 `stdio`。
* 它放在 `if __name__ == "__main__":` 之下，因为所有加载服务器的东西（`mcp dev`、`mcp run`、`mcp install`、你的测试）都会**导入**这个文件。这个保护条件防止一次导入变成一个运行中的服务器。

### stdio {#stdio}

没有什么需要配置的。宿主把你的文件作为子进程启动，把请求写入它的 stdin，再从它的 stdout 读取响应。

自己运行一下，就能看出这意味着什么：

```console
python server.py
```

什么也不打印，也不返回。它在 stdin 上等着宿主先开口。

这也意味着 stdout **就是线路**。服务期间，SDK 把线路移到一个私有描述符上，并把**刷新**到 stdout 的输出（子进程写入它继承的 stdout、刷新过的 `print()`）转到 stderr，在那里不会破坏数据流。在开始服务**之前**就刷新到 stdout 的输出（包装脚本的 echo、导入时的无缓冲 print）仍然会落到线路上；一直缓冲到解释器退出时才排空的 `print()` 也一样。对于真正想要的输出，`logging` 模块才是正确的工具：它的 handler 会在每条记录产生时就把它刷新到 stderr。详见 **[日志记录](../handlers/logging.md)**。

### 试一试 {#try-it}

```console
uv run mcp dev server.py
```

Inspector 做的事和真实宿主完全一样：它把 `server.py` 作为子进程启动，通过 stdio 连接它。

你从没给过它端口。根本就没有端口。

## Streamable HTTP {#streamable-http}

要把同一个服务器放到端口上，在 `run()` 里指明传输方式（及其选项）：

```python title="server.py" hl_lines="13"
--8<-- "docs_src/run/tutorial002.py"
```

这一行会构建一个 Starlette 应用并用 uvicorn 提供服务。客户端连接到 `http://127.0.0.1:3001/mcp`。

每种传输方式都有自己的关键字参数，全都在 `run()` 上：

* `host` / `port`：监听的位置。默认 `127.0.0.1` 和 `8000`。
* `streamable_http_path`：MCP 端点所在的路径。默认 `/mcp`。
* `json_response=True`：用单个 JSON 正文回应每个 POST，而不是 SSE 流。这个正文只容得下响应本身，别的什么都放不下，所以在请求中途回调客户端的工具（`ctx.elicit()`、采样（sampling））会在这一段抛出 `NoBackChannelError`；与进行中的调用绑定的通知（`ctx.report_progress()` 的进度、每次调用的日志消息）会被丢弃；独立的 `GET` 流仍然承载与之无关的通知。
* `stateless_http=True`：每个请求一个全新的传输，不跟踪会话。
* `max_request_body_size`：接受的最大 POST 正文大小，单位为字节。默认 4 MiB；更大的请求在解析或创建会话之前就会收到 HTTP 413。只有当合法的 MCP 消息确实超过这个大小时才调高它。
* `event_store`、`retry_interval`、`transport_security`：可恢复性和 DNS 重绑定防护。它们可以先放一放，等部署到 localhost 以外的地方再说；**[部署与扩展](deploy.md)** 介绍了 `transport_security`。

!!! warning
    传输选项传给 `run()`，**不是** `MCPServer(...)`。构造函数描述服务器**是什么**：名称、版本、说明。`run()` 描述它如何对外提供服务。搞反了，Python 在 MCP 介入之前就会报错：

    ```text
    TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'
    ```

`run()` 是捷径。一旦需要更多（把服务器挂载到现有应用里、一个进程里跑两个服务器、为浏览器客户端配置 CORS），就要自己构建 ASGI 应用，再交给任意 ASGI 服务器运行。这就是 **[添加到现有应用](asgi.md)** 的内容。

## 服务器设置 {#server-settings}

运行方面有几件事与传输方式无关。它们是构造函数参数：

```python title="server.py" hl_lines="3"
--8<-- "docs_src/run/tutorial003.py"
```

* `log_level`：在构造 `MCPServer(...)` 的那一刻传给 `logging.basicConfig()`。它配置的是**根** logger，所以也会设置你自己的 logger 的级别，而不只是 SDK 的。默认 `"INFO"`。
* `debug`：转发给 HTTP 传输构建的 Starlette 应用。默认 `False`。

两者都落在 `mcp.settings` 上，可以在运行时读回。

## `mcp` 命令 {#the-mcp-command}

`[cli]` 附加依赖会安装一个把这些都包起来的小型命令行工具。

`mcp dev` 在 **MCP Inspector** 下运行你的服务器：

```console
uv run mcp dev server.py
uv run mcp dev server.py --with pandas --with numpy
uv run mcp dev server.py --with-editable .
```

`--with` 往它构建的环境里添加包；`--with-editable` 把你自己的包安装进去。它需要 `PATH` 上有 `npx`：Inspector 是一个 Node.js 应用。

`mcp run` 导入文件，找到服务器对象（模块级的 `mcp`、`server` 或 `app`），然后对它调用 `run()`：

```console
uv run mcp run server.py
uv run mcp run server.py:bookshop
```

当对象不叫 `mcp`、`server` 或 `app` 时，用 `:` 后缀指明它的名字。

在这里，`if __name__ == "__main__":` 块永远不会执行：`mcp run` 自己调用 `run()`，它唯一转发的选项是 `--transport`。

`mcp install` 把服务器注册到 **Claude Desktop**，让这个应用替你启动它：

```console
uv run mcp install server.py --name "Bookshop"
uv run mcp install server.py -v API_KEY=abc123 -f .env
```

`-v KEY=VALUE` 和 `-f .env` 把环境变量记录在该条目里。Claude Desktop 在它自己的进程里启动你的服务器，你 shell 里的环境变量那里没有。

Claude Desktop 是 `mcp install` 唯一认识的宿主。其他宿主（Claude Code、Cursor、VS Code）都在各自的配置文件里接受同样的启动命令，**[连接到真实的宿主](../get-started/real-host.md)** 逐一介绍了它们。

`mcp version` 打印已安装的 SDK 版本。

!!! tip
    `mcp dev` 和 `mcp run` 只认 `MCPServer`。如果用底层的 `Server` 构建，就要自己运行它。见 **[底层 Server](../advanced/low-level-server.md)**。

## 回顾 {#recap}

* **传输方式**是字节到达服务器的方式：本地子进程用 `stdio`，端口用 `streamable-http`。SSE 已被取代。
* `mcp.run()` 选择传输方式。不带参数时是 `stdio`，并且会阻塞。
* 每个传输选项（`host`、`port`、`streamable_http_path`……）都是 `run()` 的参数，绝不是 `MCPServer(...)` 的。
* 把 `run()` 放在 `if __name__ == "__main__":` 之下。所有加载服务器的东西都会先导入这个文件。
* `log_level=` 和 `debug=` 是构造函数参数；它们落在 `mcp.settings` 上。
* `mcp dev` 用于 Inspector，`mcp run` 执行文件，`mcp install` 用于 Claude Desktop，`mcp version` 查看版本。
* 传输方式永远不会改变服务器**是什么**：本页的三个文件暴露的是完全相同的工具。

当 `run()` 本身成了限制（服务器要放进一个已经存在的应用里），看 **[添加到现有应用](asgi.md)**。需要真正的主机名和不止一个 worker，看 **[部署与扩展](deploy.md)**。如果有些客户端还停留在 2025-11-25 或更早的规范版本，**[为旧版客户端提供服务](legacy-clients.md)** 有好消息。
