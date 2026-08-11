---
translation:
  sections: [1062ef792791488a, 4be2b831547184a9, 374b049e770385f2, b72f6947089e6de0, b172c9db7831bb31, 70b9ece244ca1b0c, cba78e052898c3f6, f06bdb541cb0b469, fb82d526320b7cc3]
  tool: 1
---
# 添加到现有应用 {#add-to-an-existing-app}

`mcp.run("streamable-http")` 会替你启动一个 Web 服务器。有时你并不想这样：MCP 服务器只是一个更大的 Web 应用的一部分，或者你已经有现成的 ASGI 部署。

为此，`mcp.streamable_http_app()` 会返回一个 **Starlette 应用**。

Starlette 应用就是 ASGI 应用，所以任何能承载 ASGI 的东西（uvicorn、Hypercorn、另一个 Starlette、FastAPI）都能承载你的 MCP 服务器。

## 应用 {#the-app}

```python title="server.py" hl_lines="12"
--8<-- "docs_src/asgi/tutorial001.py"
```

`app` 是一个普通的 ASGI 应用。把它交给任意 ASGI 服务器即可：

```console
uvicorn server:app
```

MCP 端点位于 `/mcp`，所以客户端连接的是 `http://127.0.0.1:8000/mcp`。

这个应用已经自带两样东西：

* 一条路由 `/mcp`：Streamable HTTP 端点。
* 一个**生命周期**，用来启动 `mcp.session_manager`——这个对象掌管每个活跃会话的后台工作。

单独运行这个应用（`uvicorn server:app`）时，这两样都不用你操心。

!!! tip
    `streamable_http_app()` 接受与 `mcp.run("streamable-http", ...)` 相同的关键字参数，只是少了 `port`：端口归负责承载该应用的那一方管。`host` 仍然可以传，但在这里不绑定任何东西；它实际控制什么，**[部署与扩展](deploy.md)** 有说明。各选项本身见 **[运行服务器](index.md)**。

`mcp.sse_app()` 为已被取代的 SSE 传输做同样的事。

## 默认只响应 localhost，除非你另行指定 {#localhost-only-until-you-say-otherwise}

默认情况下，这个应用**只**响应发往 localhost 的请求。`streamable_http_app()` 无从知道自己会被部署在哪个主机名后面，所以它以最保守的允许列表启用 DNS 重绑定防护；在你自己的机器上，这正合适。部署到真实主机名后面时，这意味着**每个请求都会被以 `421 Misdirected Request` 拒绝**，直到你通过 `transport_security=` 传入一份你实际提供服务的主机名允许列表。在那之前，你写的任何东西都不会被调用。这份允许列表，以及从一个能跑的应用到真实主机名之间的其他一切，详见 **[部署与扩展](deploy.md)**。

## 挂载 {#mounting-it}

一旦 MCP 服务器成为更大应用的**一部分**，就要把这个应用放进一个 `Mount` 里。而一旦这么做，生命周期就成了你的事：

```python title="server.py" hl_lines="18-21 25-26"
--8<-- "docs_src/asgi/tutorial002.py"
```

* `Mount("/", ...)` 加上默认的 `/mcp` 路径，端点仍在 `/mcp`。Starlette 按顺序尝试路由，而 `Mount("/")` 会匹配**所有**路径，所以你自己的路由要放在列表里它的**前面**。排在它后面的都无法访问。
* `lifespan` 函数在**宿主**应用的整个生命周期内进入 `mcp.session_manager.run()`。这是人人都会忘的那一行。
* `mcp.session_manager` 只有在调用过 `streamable_http_app()` **之后**才存在。所以路由在模块层面就构建好，而会话管理器只在生命周期函数内部才去访问。

Starlette 的 `Host` 路由用法相同：把 `Mount("/", ...)` 换成 `Host("mcp.example.com", ...)`，就改为按主机名而不是按路径来路由。生命周期的规则不变，传输安全的规则也不变。`Host("mcp.example.com", ...)` 路由只会收到发往该主机名的请求，但传输自身的 Host 允许列表（**[部署与扩展](deploy.md)**）仍然先执行。列表里没有 `"mcp.example.com"` 的话，这条路由对每一个请求都回以 `421`。

!!! warning "生命周期归宿主应用管"
    `streamable_http_app()` 把 `session_manager.run()` 接入了它返回的 Starlette 的生命周期，但**被挂载的子应用的生命周期永远不会运行**。一旦挂载，这个内置的生命周期就成了死代码。无论哪个应用位于 ASGI 栈的最顶层，都必须在自己的生命周期里进入 `mcp.session_manager.run()`。

!!! check
    删掉 `lifespan=lifespan` 这一行再启动服务器。能启动，路由也能解析。然后对 `/mcp` 的第一个请求会失败：

    ```text
    RuntimeError: Task group is not initialized. Make sure to use run().
    ```

    除了它的 `run()`，没有别的东西会启动会话管理器。

## 两个服务器，一个应用 {#two-servers-one-app}

每个 `MCPServer` 都是独立的应用，带有自己的会话管理器。想挂载多少就挂载多少；在同一个宿主生命周期里进入每一个管理器：

```python title="server.py" hl_lines="27-30 35-36"
--8<-- "docs_src/asgi/tutorial003.py"
```

* `AsyncExitStack` 进入两个管理器；它们一起启动，按相反顺序关闭。
* 端点是 `/notes/mcp` 和 `/tasks/mcp`：挂载前缀加默认路径。

## 更改路径 {#changing-the-path}

末尾的那个 `/mcp` 就是 `streamable_http_path`。把它设为 `"/"`，挂载前缀就成了完整的公开路径：

```python title="server.py" hl_lines="25"
--8<-- "docs_src/asgi/tutorial004.py"
```

现在客户端连接 `/notes`，而不是 `/notes/mcp`。

## 面向浏览器客户端的 CORS {#cors-for-browser-clients}

基于浏览器的客户端需要你给两项许可：**发送**它的 MCP 请求头，以及**读取** MCP 返回的那个响应头。两者都是宿主应用上的 CORS 配置，而且上面的传输安全允许列表必须与之一致：

```python title="server.py" hl_lines="27-30 33 35-49"
--8<-- "docs_src/asgi/tutorial005.py"
```

* `allow_headers` 是人人都会忘的那一半。浏览器会对每个 MCP 请求做**预检**，因为 `Content-Type: application/json` 和 `Mcp-*` 请求头都不在 CORS 安全列表里，而预检没有放行的头，就意味着浏览器根本不会发出这个请求。（`allow_headers=["*"]` 也行：Starlette 会按预检请求所要求的内容原样应答。）
* `expose_headers=["Mcp-Session-Id"]` 是读取那一半。Streamable HTTP 在这个响应头里返回会话 ID，而浏览器会对 JavaScript 隐藏响应头，除非 CORS 按名称公开它们。没有它，客户端永远发不出第二个请求。
* `allow_origins` 由你决定，不归 MCP 管。写得精确些，并在上面的 `allowed_origins=` 里保持一致：CORS 由浏览器强制执行，但服务器自己也会检查 `Origin`，传输不信任的来源即使预检顺利通过，也会得到 `403`。
* `allow_methods` 列出 Streamable HTTP 用到的三个方法：`POST` 发送消息，`GET` 打开服务器到客户端的流，`DELETE` 结束会话。

## 自定义路由 {#custom-routes}

`@mcp.custom_route()` 在同一个应用上注册一个普通的 HTTP 端点，用于每个部署出去的服务都需要、却与 MCP 无关的东西：健康检查、OAuth 回调。

```python title="server.py" hl_lines="15-17"
--8<-- "docs_src/asgi/tutorial006.py"
```

* 处理函数就是普通的 Starlette：一个从 `Request` 到 `Response` 的 `async` 函数。
* `streamable_http_app()` 会收进每一条自定义路由。`app.routes` 现在是 `/mcp` 和 `/health`。
* `GET /health` 应答 `{"status": "ok"}`，完全不涉及 MCP。

!!! warning
    自定义路由**永远不做认证**，即使服务器的其余部分做了。这是有意为之：健康检查和 OAuth 回调必须在任何令牌存在之前就能访问。不要把任何私密内容放在它后面。

## 回顾 {#recap}

* `mcp.streamable_http_app()` 返回一个只有一条路由 `/mcp` 的 Starlette 应用。任何 ASGI 服务器都能运行它。
* 默认情况下这个应用只响应发往 localhost 的请求；部署在真实主机名后面时，在你通过 `transport_security=` 传入允许列表之前，它会以 `421` 拒绝一切。这件事，以及通往生产环境的其余路程，都归 **[部署与扩展](deploy.md)** 管。
* `Mount`（或 `Host`）把它放进更大的 Starlette 或 FastAPI 应用。
* **挂载会让内置生命周期失效。**宿主应用的生命周期必须进入 `mcp.session_manager.run()`，否则第一个请求就会失败。
* 一个应用里放多个服务器，意味着多个挂载，加上一个进入每个会话管理器的生命周期。
* `streamable_http_path="/"` 把端点移到挂载前缀本身。
* 浏览器客户端需要 CORS：`allow_headers` 放行 `Mcp-*` 请求头，`expose_headers=["Mcp-Session-Id"]` 公开响应头。
* `@mcp.custom_route()` 在 `/mcp` 旁边添加普通的、不做认证的 HTTP 端点。

服务器一旦能通过真实 URL 访问，**[客户端](../client/index.md)** 就可以用这个 URL 而不是服务器对象来连接它。
