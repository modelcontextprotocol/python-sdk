---
translation:
  sections: [c6899d3892bd9fa0, 79372cff3cc48a88, 63878d29e87c3e73, 13175843d3588af4, e7e2b9fd516f77de, 758f06399b513c1f, a05d7278487d610b]
  tool: 1
---
# OAuth 客户端 {#oauth-clients}

有些 MCP 服务器是受保护的。不带令牌向它们发送请求，它们会回答 `401 Unauthorized`。

**`OAuthClientProvider`** 就是获取令牌的办法。它根本不是 MCP 对象，而是一个 `httpx2.Auth`，也就是 httpx2 中“对每个请求做点什么”的标准钩子。把它挂到 `httpx2.AsyncClient` 上，把这个客户端交给 Streamable HTTP 传输，然后就不用再管它了。

本页讲的是客户端一侧。让你自己的服务器要求令牌，见 **[授权](../run/authorization.md)**。

## 提供者 {#the-provider}

```python title="client.py" hl_lines="44-54"
--8<-- "docs_src/oauth_clients/tutorial001.py"
```

需要给它四样东西：

* `server_url`：要连接的 MCP 端点。提供者从它出发发现其余一切。
* `client_metadata`：你会在授权服务器的“注册应用”表单里填写的内容。
* `storage`：令牌在多次运行之间存放的地方。
* `redirect_handler` 和 `callback_handler`：需要人参与的两个时刻。

文件里其他地方都没有提到 OAuth。`main()` 从头到尾看不到令牌。

### 客户端元数据 {#client-metadata}

`OAuthClientMetadata` 就是真正的 [RFC 7591](https://datatracker.ietf.org/doc/html/rfc7591) 注册文档，以 Pydantic 模型的形式存在。

只需设置三个字段，其余由默认值补齐：`grant_types` 已经是 `["authorization_code", "refresh_token"]`，`response_types` 已经是 `["code"]`，正好是这个提供者运行的流程。

!!! check
    因为它是 Pydantic 模型，所以**在任何一个字节发到网络之前**就会校验。漏掉 `redirect_uris`，构造当场失败，抛出的 `ValidationError` 会点名该字段：

    ```text
    redirect_uris
      Field required [type=missing, input_value={'client_name': 'Bookshop Agent'}, input_type=dict]
    ```

    没有打开浏览器，也不会在授权服务器上留下注册了一半的记录。

### 令牌存储 {#token-storage}

**`TokenStorage`** 是一个带四个异步方法的 `Protocol`。不用继承任何东西；写出这些方法，任何类就都是令牌存储：

* `get_tokens` / `set_tokens` 保存 `OAuthToken`：访问令牌、刷新令牌、过期时间、作用域。
* `get_client_info` / `set_client_info` 保存提供者替你注册时授权服务器颁发的 `OAuthClientInformationFull`，其中包含你的 `client_id`。

上面的内存版本可以工作。但进程退出时它会忘掉一切，于是下一次运行又要把整套流程重走一遍。把它持久化到文件或平台的密钥环里，下一次运行就悄无声息了。

!!! tip
    要存 `client_info`，而不只是令牌。提供者在第一次找不到已存的 `client_info` 时会动态注册。把它扔掉，每次运行都会生成一个全新的注册。

### 两个处理函数 {#the-two-handlers}

授权码流程恰好需要人参与一次：得有人登录并点击“允许”。

* **`redirect_handler`** 会以构建完整的授权 URL 为参数被 await。`client_id`、`redirect_uri`、`state` 和 PKCE challenge 都已经在里面了。你唯一要做的是让浏览器打开它。桌面应用调用 `webbrowser.open`；这个文件把它打印出来。
* **`callback_handler`** 紧接着被 await。它一直等到用户回到你的 `redirect_uri`，然后把那次重定向的查询参数作为 `AuthorizationCodeResult` 返回。

真实的客户端会在重定向 URI 上运行一个小型本地 HTTP 服务器，而不是调用 `input()`。形式完全一样：被重定向，交回 `code`、`state` 和 `iss`。

!!! warning
    `state` 和 `iss` 要原样传递，收到什么就交回什么。提供者会把 `state` 与自己生成的值比较，把 `iss` 与发现到的颁发者比较，不匹配就拒绝。它们分别是 CSRF 防御和服务器混淆防御。

### 接入 `Client` {#into-the-client}

看一下 `main()`。提供者挂在 **httpx2 客户端**上，httpx2 客户端传入 `streamable_http_client(url, http_client=...)`，这个传输再传入 `Client`。

`streamable_http_client` 没有 `auth=` 关键字。所有 HTTP 层面的东西（认证、请求头、超时、代理）都属于你自己带来的 `httpx2.AsyncClient`。这种分层详见 **[客户端传输](transports.md)**。

## 提供者替你做了什么 {#what-the-provider-does-for-you}

`Client` 第一次发送请求时，服务器回答 `401`。提供者接手：

1. **发现。** 它读取 `WWW-Authenticate` 头，从 `/.well-known/oauth-protected-resource` 获取服务器的受保护资源元数据，得知是哪个授权服务器在保护这个资源，再去获取**那个**服务器的元数据。
2. **注册。** 存储里什么都没有？它用你的 `OAuthClientMetadata` 动态注册，并把结果存起来。
3. **授权。** 它生成 PKCE 对和一个 `state`，构建授权 URL，await 你的 `redirect_handler`，然后 await 你的 `callback_handler` 拿到授权码。
4. **交换。** 它用授权码换来 `OAuthToken`，存起来，再带上 `Authorization: Bearer ...` 重放你最初的请求。

之后它就安静了。令牌从存储里取出，过期的访问令牌用刷新令牌刷新，只有这些都行不通时才会重新跑一遍流程。

这些你一行都没写。还剩两个关键字参数（`client_metadata_url` 和 `validate_resource_url`），这个文件都用不到。值得了解的是 `client_metadata_url`，下面单独有一节讲它。

### 试一试 {#try-it}

这份文档里的大多数示例都可以用内存中的 `Client(server)` 验证。这个不行：整个流程的核心就是一个 HTTP `401`，而内存中的客户端和它的服务器之间没有 HTTP。

仓库里附带了可实际运行的版本。`examples/servers/simple-auth/` 运行一个独立的授权服务器和一个受保护的 MCP 服务器；`examples/clients/simple-auth-client/` 是本页的客户端扩展成的一个小 CLI。它的 README 里有两条命令：启动服务器，对着它们运行客户端，就能看到这四个步骤依次走过。

## Client ID Metadata Documents {#client-id-metadata-documents}

规范的 2026-07-28 修订版弃用了动态客户端注册，改用 **Client ID Metadata Documents**（CIMD）。客户端不再向遇到的每个授权服务器 POST 一份新的注册，而是在一个稳定的 HTTPS URL 上发布一份描述自己的 JSON 文档，这个 URL **就是**它的 `client_id`。授权服务器去获取这份文档；提供者从不碰它。

SDK 已经支持它：构造提供者时把这个 URL 作为 `client_metadata_url=` 传入。当授权服务器的元数据声明了 `client_id_metadata_document_supported: true` 时，提供者会完全跳过 `/register` 请求：URL 作为 `client_id` 进入流程，没有 `client_secret`。当服务器没有声明它（目前大多数还没有），或者你没有传 URL 时，提供者会**悄悄地**回退到动态注册，上面的一切照常工作。已存的 `client_info` 仍然优先于这两者。

URL 必须是 HTTPS 且路径不能是根路径；否则在构造时就是 `ValueError`，不会发生任何网络请求。附带的 `examples/clients/simple-auth-client/` 通过环境变量 `MCP_CLIENT_METADATA_URL` 接收它。

## 机器对机器 {#machine-to-machine}

夜间任务、CI 步骤、另一个服务。没有浏览器，也没人来点“允许”。这就是 **client credentials** 授权方式：你手里已经有 `client_id` 和 `client_secret`，令牌端点就是整个流程。

`ClientCredentialsOAuthProvider` 是同一个 `httpx2.Auth`，只是去掉了人：

```python title="client.py" hl_lines="4 27-33"
--8<-- "docs_src/oauth_clients/tutorial002.py"
```

变了什么：

* 没有 `OAuthClientMetadata`，没有处理函数。传入 `client_id` 和 `client_secret`；提供者围绕它们构建一个最小的 `client_credentials` 注册，完全跳过动态注册。
* `scope` 是空格分隔的字符串，即 OAuth 的线路格式。
* 下游的一切完全相同：同样的 `TokenStorage`、同样的 `httpx2.AsyncClient(auth=...)`、同样的 `streamable_http_client`。

默认情况下，密钥在令牌请求里以 HTTP Basic 认证的方式传送（`client_secret_basic`）。传入 `token_endpoint_auth_method="client_secret_post"` 可以改为把它放进表单体。有些授权服务器只接受两者之一。

!!! tip
    从环境变量或密钥管理器读取 `client_secret`，绝不要从源码版本控制里读。

!!! info
    `mcp.client.auth.extensions.client_credentials` 里还有一个提供者：**`PrivateKeyJWTOAuthProvider`**，用于以 JWT 而非共享密钥进行认证的客户端（`private_key_jwt`，即密钥对和工作负载身份那一类）。它遵循同样的模式：构造一个，放到 `auth=` 上。同一个模块还附带 `SignedJWTParameters` 和 `static_assertion_provider`，两个用来构建其断言的辅助工具。

还有一种没有人参与的情形：客户端属于某个企业，由企业的身份提供者而不是用户来决定它可以访问哪些 MCP 服务器。那是另一种授权方式，有自己的信任模型和自己的页面，**[身份断言](identity-assertion.md)**。

## 出错时 {#when-it-fails}

OAuth 流程出错时，提供者会抛出 `mcp.client.auth` 里的 `OAuthFlowError`。它有两个子类。`OAuthRegistrationError` 表示注册没有产生一个可用的客户端：授权服务器拒绝为你注册，或者它确实注册了，但给出的凭据这个流程用不了（比如它没有实现的认证方法）。`OAuthTokenError` 表示无法获取令牌：令牌端点拒绝了，或者已存的客户端记录带有这个客户端无法应用的认证方法，这种情况在构建令牌请求时就会报告，而不会发送出去。一个 `except OAuthFlowError:` 就覆盖了发现、注册、授权和交换。

并非一切都是流程错误。网络仍然可能失败；那些是普通的 `httpx2` 异常，会原样透传。

## 回顾 {#recap}

* `OAuthClientProvider` 是一个 `httpx2.Auth`。把它放到 `httpx2.AsyncClient` 上，再把后者传给 `streamable_http_client(url, http_client=...)`，`Client` 永远不知道发生过 OAuth。
* 你提供四样东西：服务器 URL、一个 `OAuthClientMetadata`、一个 `TokenStorage`，以及 redirect/callback 处理函数对。
* `TokenStorage` 是一个 `Protocol`：四个异步方法，没有基类。除了令牌，也要持久化 `client_info`。
* 发现、注册（动态注册，或通过 **Client ID Metadata Document**）、PKCE、`state` 和 `iss` 检查，以及令牌刷新，都是提供者的事，不是你的。
* `ClientCredentialsOAuthProvider` 是无人参与的版本：`client_id` + `client_secret`，没有处理函数，没有浏览器。
* 每个 OAuth 失败都是 `OAuthFlowError`；`OAuthRegistrationError` 和 `OAuthTokenError` 是它的子类。

这次握手的另一半，让你的**服务器**要求令牌，见 **[授权](../run/authorization.md)**。
