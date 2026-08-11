---
translation:
  sections: [d62c13457fc4a534, 80e73abaca6e0652, d1dc4c54cd00ec9c, 14ad3bc7904036bb, 5225f127bc1b9c77, fe1626fdd5aad1da, 4556cb7ea1a04a31]
  tool: 1
---
# 授权 {#authorization}

通过 Streamable HTTP 运行时，你的 MCP 服务器就是一个普通的 Web 服务，保护它的方式也和保护其他 Web 服务一样：用 OAuth 2.1 bearer token。

用 OAuth 的术语说，你的服务器是**资源服务器**。它从不负责任何人的登录，也从不签发 token。它只做一件事：查看每个请求的 `Authorization` 头，判断其中的 token 是否有效。

本页讲的是服务器端。负责发现你的授权服务器并获取 token 的客户端，见 **[OAuth 客户端](../client/oauth-clients.md)**。

## 三方角色 {#the-three-parties}

* **授权服务器**负责用户登录并签发访问 token。这部分不用你写，它就是你的身份提供方（Auth0、Keycloak、Entra，或者你自己的）。
* **资源服务器**就是你的 MCP 服务器。它在每个请求上验证 token。
* **客户端**发现你信任的是哪个授权服务器，从那里拿到 token，再以 `Authorization: Bearer <token>` 的形式发回给你。

整个三角关系就是这样。本页所有内容都是中间那一条。

## Token 验证器 {#a-token-verifier}

有效的 token 长什么样，SDK 没有任何预设。这由你来决定，方式是实现 **`TokenVerifier`**：

```python title="server.py" hl_lines="12-14 19-24"
--8<-- "docs_src/authorization/tutorial001.py"
```

* `TokenVerifier` 是一个只有一个异步方法的协议。`verify_token` 接收 `Authorization` 头里的原始 token，有效时返回一个 **`AccessToken`**，无效时返回 `None`。除此之外没有别的要实现。
* 这个例子是在一张表里查找 token。真实的实现会验证 JWT 签名，或者调用授权服务器的 token 自省端点。那部分代码是你的，SDK 只负责调用它。
* `token_verifier=` 和 `auth=` 永远成对出现。只传其中一个，`MCPServer(...)` 会在处理任何请求之前就抛出 `ValueError`。

`AuthSettings` 是你的资源服务器对外的门面：

* `issuer_url`：签发你的 token 的授权服务器。
* `resource_server_url`：这个 MCP 端点的公开 URL。它指明 token 是针对**哪一个**资源的，发现文档也位于这里。
* `required_scopes`：每个 token 都必须携带其中全部 scope。

!!! tip "提示"
    SDK 仓库中的 `examples/servers/simple-auth/` 有一个 `IntrospectionTokenVerifier`，它会调用真实授权服务器的 [RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662) 端点。大多数生产环境的验证器都是这个样子。

## 通过 HTTP 能得到什么 {#what-you-get-over-http}

授权信息存在于 HTTP 头中，所以它只存在于 HTTP 传输方式上。在你部署用的那一种上运行它：`mcp.run(transport="streamable-http")` 会把它放在 `http://127.0.0.1:8000/mcp`，其余内容详见 **[运行你的服务器](index.md)**。现在这个应用有两个路由：

```text
/mcp
/.well-known/oauth-protected-resource/mcp
```

你注册了一个工具。第二个路由是 SDK 的。

### 发现 {#discovery}

对那个 well-known 路径发 `GET` 请求，会得到 **[RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata**，直接由你的 `AuthSettings` 构建而来：

```json
{
  "resource": "http://127.0.0.1:8000/mcp",
  "authorization_servers": ["https://auth.example.com/"],
  "scopes_supported": ["notes:read"],
  "bearer_methods_supported": ["header"]
}
```

一个从没听说过你服务器的客户端就是靠这份文档找到入口的：它读取 `authorization_servers`，然后去那里获取 token。这些一行都不是你写的。

!!! check "检查"
    不带 token（或者带一个你的验证器返回了 `None` 的 token）调用 `/mcp`，请求会被挡在门外：

    ```text
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"

    {"error": "invalid_token", "error_description": "Authentication required"}
    ```

    什么都没有被解析，也没有工具运行。而 `WWW-Authenticate` 里那个 `resource_metadata` 指针，正是让发现过程自动完成的关键：401 -> 元数据文档 -> 授权服务器 -> token -> 重试。

!!! warning "警告"
    这些都保护不了 `stdio`。管道没有 `Authorization` 头，所以在那里永远不会询问 `token_verifier`。`stdio` 服务器的安全边界是启动它的那个进程。测试中使用的内存内 `Client(mcp)` 也一样：它直接连接到服务器对象，跳过了 HTTP 层，授权也包括在内。

## 调用者的身份 {#the-callers-identity}

在任何处理函数内部，**`get_access_token()`** 就是你的验证器为当前请求返回的那个 `AccessToken`：

```python title="server.py" hl_lines="4 32-35"
--8<-- "docs_src/authorization/tutorial002.py"
```

* 它在工具、资源和提示词中都能用，而且不需要传递任何东西：认证中间件按请求把它存在一个上下文变量里。
* 你拿回的是**你的验证器构建的同一个对象**：`client_id`、`scopes`、`subject`、`expires_at`，以及你附加的任何额外 `claims`。这就是按工具制定规则的切入点：读取 scope，然后拒绝。
* 在经过认证的 HTTP 请求之外，它返回 `None`。在内存内和通过 `stdio` 时，它永远是 `None`。

带上 `Authorization: Bearer alice-token` 调用 `whoami`，模型会读到：

```text
alice (scopes: notes:read)
```

## SDK 不做的那一半 {#the-half-the-sdk-doesnt-do}

SDK 给你的是资源服务器这一半：验证、公布、拒绝。它不提供登录页、同意授权页，也不提供 token。

想看三方如何协作，可以运行 SDK 仓库里的 `examples/servers/simple-auth/`（一个小型授权服务器，加上一个配置与本页完全相同的资源服务器），再把 `examples/clients/simple-auth-client/` 指向它，走一遍完整的发现与获取 token 的流程。

!!! info "信息"
    还有第二个构造函数参数 `auth_server_provider=`，它会在你的 MCP 服务器内部嵌入一个完整的授权服务器。它早于 MCP 授权规范所围绕的 AS/RS 分离。新的服务器不应该去用它。

授权服务器也可以接受企业身份提供方签名的断言，代替用户点击同意授权页，SDK 对这个交换的两端都提供支持。这种授权方式以及出示它的客户端，见 **[身份断言](../client/identity-assertion.md)**。

## 回顾 {#recap}

* 通过 Streamable HTTP 运行时，你的服务器是 OAuth 2.1 **资源服务器**：它验证 token，从不签发 token。
* `TokenVerifier` 是全部的集成接口：一个异步方法，传入 token，返回 `AccessToken | None`。
* `token_verifier=` 和 `auth=AuthSettings(issuer_url=..., resource_server_url=..., required_scopes=[...])` 永远成对出现。
* SDK 在 `/.well-known/oauth-protected-resource/...` 发布 [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728) Protected Resource Metadata，并对未认证的请求回应 401，其 `WWW-Authenticate` 头指向该文档。整个发现过程就是这样。
* 在任何处理函数里，`get_access_token()` 就是调用者是谁。
* 授权是 HTTP 层面的事。`stdio` 和内存内客户端永远看不到它。

客户端那一半（发现你的授权服务器并替你获取 token）见 **[OAuth 客户端](../client/oauth-clients.md)**。而一个**断言**身份、而不是向用户索要身份的客户端，见 **[身份断言](../client/identity-assertion.md)**。
