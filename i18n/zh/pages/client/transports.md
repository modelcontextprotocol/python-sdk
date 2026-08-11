---
translation:
  sections: [9cac816674181eb0, 0700f337babcd4dd, 2bde0dd58cdf00f5, ff7401df479af877, 3d0832f39b0d7059, d4bf7e4479637768, 05e20c0a798860e7]
  tool: 1
---
# 客户端传输 {#client-transports}

每个 `Client` 都通过一种**传输**与它的服务器通信：真正承载消息的那一层。

你从来不需要单独配置它。`Client` 只接受一个位置参数，并根据它的类型推断出传输方式。

每种传输的**服务器**一侧（`mcp.run()` 做什么、你部署什么）见 **[运行你的服务器](../run/index.md)**。

## 内存中 {#in-memory}

传入服务器对象本身：

```python title="client.py" hl_lines="14"
--8<-- "docs_src/client_transports/tutorial001.py"
```

没有子进程，没有端口，线路上没有任何字节。客户端和服务器是同一个进程里的两个对象，而调用仍然走真实的协议层：`search_books` 的列出、校验和调用，和走 HTTP 时完全一样。

这让它同时具有两种用途：

* **测试支架。** 本文档中的每个示例都是这样跑通的，**[测试](../get-started/testing.md)** 页面围绕它构建了整套模式。
* **嵌入 API。** 自己构造服务器的应用不需要经过网络就能调用它的工具。

## Streamable HTTP {#streamable-http}

传入一个 URL 字符串，得到的就是 **Streamable HTTP**，也就是部署时用的传输方式：

```python title="client.py" hl_lines="5"
--8<-- "docs_src/client_transports/tutorial002.py"
```

这就是完整的生产环境客户端。`Client` 替你把 URL 包进 `streamable_http_client(...)`，底层是一个按 MCP 的需要配置好的 `httpx2.AsyncClient`：`follow_redirects=True`，connect/write/pool 超时 30 秒，读超时 300 秒，因为服务器可能会一直保持响应流打开。

!!! check
    构造出来的 `Client` **并未**连接。构造只是选定传输方式；打开它的是 `async with`。在进入之前就去取连接，SDK 会明确告诉你：

    ```text
    RuntimeError: Client must be used within an async context manager
    ```

    写下 `Client("http://...")` 时，没有解析任何东西，没有获取任何东西，也没有启动任何进程。这一行没有任何开销。

### 自带 `httpx2.AsyncClient` {#bring-your-own-httpx2asyncclient}

一旦需要 `Authorization` 头、cookie、代理、mTLS 或不同的超时，就自己构建 `httpx2.AsyncClient`，再把它交给 `streamable_http_client`：

```python title="client.py" hl_lines="8-14"
--8<-- "docs_src/client_transports/tutorial003.py"
```

注意两点：

* `httpx2.AsyncClient` 归你所有，所以由**你**进入和退出它。SDK 从不关闭不是它自己创建的客户端。
* `streamable_http_client(url, http_client=...)` 返回一个传输，`Client(transport)` 像接受其他任何东西一样接受它。

关于 TLS 的一点说明：`httpx2` 依据操作系统的信任库（通过
[`truststore`](https://pypi.org/project/truststore/)）校验证书，而不是自带的 CA 列表。在没有可用系统 CA 库的环境（某些精简容器）中，设置标准的 `SSL_CERT_FILE`/`SSL_CERT_DIR`
环境变量，或者给你的 `httpx2.AsyncClient` 显式传入 `verify=ssl_context`（背景见
[`httpx` 和 `httpx-sse` 被 `httpx2` 取代](../migration.md#httpx-and-httpx-sse-replaced-by-httpx2)）。

!!! warning
    `streamable_http_client` 过去可以直接接受 `headers=` 和 `timeout=`。现在不行了：它只有 `url`、`http_client` 和 `terminate_on_close` 三个参数。习惯性地去用 `headers=`，会得到：

    ```text
    TypeError: streamable_http_client() got an unexpected keyword argument 'headers'
    ```

    所有 HTTP 层面的东西现在都放在你传入的那一个 `httpx2.AsyncClient` 上。

!!! info
    `httpx2` 保留了熟悉的 `httpx` API，所以只要会 `httpx`，就已经知道在这里怎么做认证、代理、事件钩子、重试和连接限制。SDK 既不在上面加东西，也不拿走什么。OAuth 也是在这里接入的：`httpx2.AsyncClient(auth=OAuthClientProvider(...))`。整个流程见 **[OAuth 客户端](oauth-clients.md)**。

## stdio {#stdio}

**stdio** 服务器是一个子进程。客户端启动它，向它的 stdin 写 JSON-RPC，从它的 stdout 读 JSON-RPC。桌面宿主就是这样在你的机器上运行服务器的：宿主**就是**这段代码加上一个 UI，而 **[连接到真实宿主](../get-started/real-host.md)** 是从宿主一侧、以配置文件的形式看到的同一种关系。

用 `StdioServerParameters` 描述进程，用 `stdio_client` 把它变成传输，再把**它**交给 `Client`：

```python title="client.py" hl_lines="4-8 12"
--8<-- "docs_src/client_transports/tutorial004.py"
```

`Client` 不接受单独的参数对象。`StdioServerParameters` 是配置；`stdio_client(server)` 才是知道如何据此启动进程的传输。一定要包一层。

离开 `async with` 块也会关停子进程：关闭 stdin，等待，如果它迟迟不退出就杀掉。你从来不需要自己清理。

!!! warning
    子进程**不会**继承你的环境。它只拿到一个最小的允许列表（POSIX 上是 `HOME`、`LOGNAME`、`PATH`、`SHELL`、`TERM` 和 `USER`），这样敏感信息就不会泄漏进一个可能不是你写的进程。

    需要 API key 的服务器在那里找不到它。用 `env=` 显式传入；这些变量会合并到允许列表之上。上面的 `BOOKSHOP_API_KEY` 做的就是这件事。

## SSE {#sse}

`sse_client(url)` 来自 `mcp.client.sse`，是被 Streamable HTTP 取代的那个 HTTP 传输。用同样的方式包一层，`Client(sse_client("http://localhost:8000/sse"))`，就能和仍在使用它的服务器通信；不要在它之上构建任何新东西。

## `Transport` 协议 {#the-transport-protocol}

对 `Client` 来说，上面这些都是同一种东西。

**传输**是任何能产出一对 `(read, write)` 消息流的异步上下文管理器：正式地说，就是 `mcp.client` 中的 `Transport` 协议。`Client` 按类型解析它的参数：服务器对象在进程内连接，`str` 变成 `streamable_http_client(url)`，其他任何东西都直接作为传输进入。正是最后这条规则让 `stdio_client(...)`、`streamable_http_client(...)` 和 `sse_client(...)` 都能放进同一个位置，也让你可以自己写一个。

## 回顾 {#recap}

* `Client(mcp)`（服务器对象）在内存中连接。用于测试和嵌入。
* `Client("http://.../mcp")`（URL）通过 Streamable HTTP 连接，即生产环境的传输方式。
* 请求头、认证、代理和超时应放在 `httpx2.AsyncClient` 上，再传给 `streamable_http_client(url, http_client=...)`。没有 `headers=` 关键字参数。
* stdio 是 `Client(stdio_client(StdioServerParameters(...)))`，绝不是单独的参数对象。
* 子进程拿到的是允许列表里的环境，不是你的环境；`env=` 往里添加。
* 传输就是任何可以 `async with x as (read, write)` 的东西。凡不是服务器对象或 URL 的参数，`Client` 都直接交给这个协议。
* 构造 `Client` 选定传输方式。`async with` 打开它。

传输打开之后，两边必须就协议版本达成一致。通常根本不用考虑它；需要考虑的时候，去看 **[协议版本](../protocol-versions.md)**。
