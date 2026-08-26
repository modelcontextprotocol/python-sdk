---
translation:
  sections: [a91322c46111d16d, 8e6fd6d6f59bb568, e7828fd2729b2c9d, a03ec26bfc678b65, 1034c653c0bcf1b0]
  tool: 1
---
# 身份断言 {#identity-assertion}

普通的 OAuth provider（**[OAuth 客户端](oauth-clients.md)**）一开始会问 MCP 服务器一个问题：“你信任哪个授权服务器？”答案指向哪里，它就跟到哪里，然后要么有人登录，要么用一个预共享密钥代替人登录。

企业不希望这两件事按服务器逐个决定。它已经在运行一个身份提供方（Okta、Microsoft Entra ID，或者自建的）；用户今天早上已经登录过它了；而且安全团队只想在这一个地方决定谁能访问什么。[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990)，即 **Enterprise-Managed Authorization** 扩展，把这个决定移到了那里。IdP 签发一个短期有效的 JWT，即 **Identity Assertion JWT Authorization Grant**，简称 **ID-JAG**：它表明**这个用户**经由**这个客户端**可以访问**这个 MCP 服务器**。客户端用它换取一个普通的访问令牌。没有浏览器，没有同意页面，没有动态注册。

本页讲的是这笔交换的两端。MCP 服务器本身完全不变：它仍然是 **[授权](../run/authorization.md)** 里的那个资源服务器，检查收到的任何令牌。

## 两次令牌请求 {#two-token-requests}

这里涉及两个不同的权威方，把它们区分清楚，这一页就懂了大半。**企业 IdP** 是你所在组织的身份提供方：它知道员工是谁，策略定在它那里，ID-JAG 由它签发。SDK 从不和它通信。**MCP 授权服务器**还是 **[授权](../run/authorization.md)** 里的那个角色：MCP 服务器元数据里指明的 issuer，负责铸造这个 MCP 服务器接受的令牌。在普通的 OAuth 流程里，这两个角色通常是同一个系统。在这里它们是两个，而整个授权许可的核心，就是后者同意信任前者。

客户端向它们各发一次令牌请求。

1. **发给企业 IdP。** 客户端用用户的登录（他们的 OpenID Connect ID token）换取 ID-JAG。这是一次 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 令牌交换，完全是你 IdP 的 API，**SDK 不发这个请求**。由你来发，在一个异步回调里。策略决定也发生在这里：IdP 说不，就根本不会签发 ID-JAG，也就没有东西可出示。
2. **发给 MCP 授权服务器。** 客户端按 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) 的 `jwt-bearer` 授权许可出示 ID-JAG（`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`，ID-JAG 作为 `assertion`），拿到访问令牌。**这是 SDK 发的请求**，而接受它，就是本页给授权服务器加的唯一一样东西。

下面的内容全是第二个请求：发送它的客户端，和回应它的授权服务器。

## 客户端 {#the-client}

**`IdentityAssertionOAuthProvider`** 位于 `mcp.client.auth.extensions.identity_assertion`。和 **[OAuth 客户端](oauth-clients.md)** 里的每个 provider 一样，它是一个 `httpx2.Auth`：构造一个，放到 `auth=` 上，把 `httpx2.AsyncClient` 交给传输。

```python title="client.py" hl_lines="49-50 53-61"
--8<-- "docs_src/identity_assertion/tutorial001.py"
```

从下往上读。

* `main()` 就是标准的 OAuth 客户端 `main()`（**[OAuth 客户端](oauth-clients.md)**），一行都没改。重点就在这：一旦 provider 存在，下游没有任何东西知道令牌是哪种授权许可产生的。
* provider 接收的是其他 provider 无法自行发现的东西：有人在授权服务器上**预先注册**好的 `client_id` 和 `client_secret`、该授权服务器的 `issuer`，以及 `assertion_provider`——一个按需返回新鲜 ID-JAG 的异步回调。
* `storage` 还是那个 `TokenStorage` 协议。只会调用那两个令牌方法；这里没有动态注册，所以也没有 `client_info` 需要记住。

### 断言提供函数 {#the-assertion-provider}

`fetch_id_jag(audience, resource)` 是唯一需要你写的代码。每次令牌交换时 await 一次，构造时绝不会调用，而且只在授权服务器的元数据取回并校验通过**之后**才调用，所以配错的 issuer 永远不会泄露断言。它的两个参数是铸造 ID-JAG 时必须带上的两个声明（claim）：`audience` 是授权服务器的 issuer（ID-JAG 的 `aud`），`resource` 是 MCP 服务器的规范标识符（ID-JAG 的 `resource`）。第三个你手里已经有了：ID-JAG 的 `client_id` 声明必须写明你传给 provider 的那个 `client_id`，否则授权服务器会拒绝交换。

它上面的 `idp_issue_id_jag` **不是你的代码**。它替身份提供方出场，在进程内签发断言，这样文件是完整的，你也能读到 ID-JAG 携带的每一个声明。真正的 `fetch_id_jag` 发的是上一节里的第一个令牌请求：对你的 IdP 做一次 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 令牌交换，由 Identity Assertion JWT Authorization Grant 草案定义，[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 正是该草案的一个 profile。已登录用户的 ID token 作为 `subject_token` 传入，`requested_token_type` 是 ID-JAG 自己的 URN（`urn:ietf:params:oauth:token-type:id-jag`），`audience` 和 `resource` 原样透传，响应里带回 ID-JAG。在你 IdP 的文档里要找的，就是这些名字下的这次交换。

!!! tip
    每次交换都会请求一个新的 ID-JAG，这正是设计意图：它是一次性的、只活几分钟的授权许可，本页的授权服务器拒绝接受同一个 ID-JAG 两次。不要缓存它。该复用的是它换来的访问令牌。

### issuer 是配置项 {#the-issuer-is-configuration}

反转就在这里。`OAuthClientProvider` 会问资源服务器该用哪个授权服务器，答案指向哪里就跟到哪里。这个 provider 拒绝这么做：`issuer` 是必填的，[RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) 元数据从这个 issuer 自己的 well-known 路径获取，令牌端点必须在这个 issuer 的源（origin）上，而且从不向资源服务器询问任何事。

扩展本身并不要求这样；这是刻意做得更严格的选择。这个客户端带着两样值得偷的东西：一个预注册的密钥和一个绑定了 audience 的断言。如果客户端任由一个被攻破的 MCP 服务器把它引向攻击者的授权服务器，这两样就都会 POST 过去。在构造时钉死 issuer，这段对话就不存在了。

!!! warning
    配置的 `issuer` 会按 RFC 8414 §3.3 的简单字符串比较与元数据文档的 `issuer` 字段对比：逐字符比较，末尾斜杠算在内，不做任何规范化。不要猜。从你的授权服务器获取 `/.well-known/oauth-authorization-server`，把它返回的 `issuer` 值照抄过来。对本页的授权服务器来说，这个值是 `https://auth.example.com/`，带斜杠，因为它的 issuer 是从 Pydantic 的 URL 对象构建的。不匹配的话，流程会停在 `OAuthFlowError: Authorization server metadata issuer
    mismatch`，此时一条凭据或断言都还没有发出。

### 机密客户端 {#a-confidential-client}

`client_secret` 是必填的；没有它，构造函数会抛出 `ValueError`。[SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 底下的 IETF profile 把这种授权许可留给机密客户端，SEP-990 要求客户端进行身份认证，而这个 SDK 通过坚持要求共享密钥来同时落实这两点。`token_endpoint_auth_method` 决定它走哪条路：`client_secret_post`（默认，放在表单体里）或 `client_secret_basic`（HTTP Basic 头）。该 profile 还允许 `private_key_jwt`；这个 provider 不支持。

!!! tip
    从环境变量或密钥管理器读取 `client_secret`，永远不要从源码仓库里读。

### provider 替你做了什么 {#what-the-provider-does-for-you}

第一个请求不带认证发出，服务器的 `401` 启动整个流程。

1. **发现。** 从配置的 issuer 的 [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) well-known 路径获取授权服务器元数据，检查文档的 `issuer` 是否匹配，并检查令牌端点是否在 issuer 的源上。
2. **断言。** await 你的 `assertion_provider`。
3. **交换。** 把 `jwt-bearer` 授权许可 POST 到令牌端点，存下 `OAuthToken`，然后带上 `Authorization: Bearer ...` 重放你原来的请求。

如果收到的 `403` 的 `WWW-Authenticate` 指明 `insufficient_scope`，会用你的 `scope` 与质询中的 scope 的并集重新执行第 2、3 步。（`scope` 从来都只是请求；本页的授权服务器只授予 ID-JAG 写明的内容，别的一概不给。）整个过程里没有刷新令牌：访问令牌过期后，下一个 `401` 会铸造一个新的 ID-JAG 再次交换，**这**正是 IdP 手里握着的杠杆。失败时的异常和 **[OAuth 客户端](oauth-clients.md)** 其余部分一样是那两个：发现和校验阶段是 `OAuthFlowError`，令牌端点拒绝时是它的子类 `OAuthTokenError`。

## 授权服务器 {#the-authorization-server}

大多数时候到这里就可以停了。MCP 授权服务器是别人的产品，接受 ID-JAG 是它那边要打开的配置，SDK 负责的那一半 [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 就是上面的客户端。

SDK 也可以自己**充当**授权服务器：`create_auth_routes` 以列表形式返回授权服务器的路由，任何 Starlette 应用都能挂载，仓库里的 `examples/servers/simple-auth/` 就是这样跑起一个的。SEP-990 给这个接口面加了一个开关和一个方法：

```python title="auth_server.py" hl_lines="48-50 105-107"
--8<-- "docs_src/identity_assertion/tutorial002.py"
```

* `identity_assertion_enabled=True` 是总开关。关闭时（这是默认），即使你实现了钩子，`/token` 对这种授权许可也回答 `unsupported_grant_type`，元数据里也不会提到它。打开后，元数据会多出 `jwt-bearer` 授权类型，并在 `authorization_grant_profiles_supported` 里列出 `urn:ietf:params:oauth:grant-profile:id-jag`，这是扩展用来宣告支持的字段。（这个 SDK 的客户端从不读它：它只为一个 issuer 配置，直接发请求就是了。）
* **`exchange_identity_assertion`** 就是那个钩子。它运行之前，SDK 已经认证了客户端，拒绝了公开客户端，也拒绝了注册信息里没有列出该授权许可的客户端。你拿到一个 `IdentityAssertionParams`（原始的 `assertion`、请求的 `scopes` 和 `resource`），返回一个普通的 `OAuthToken`。
* 动态客户端注册无条件拒绝这种授权许可，所以这里的 `get_client` 提供的是一个手工配置的客户端。ID-JAG 客户端没法靠自我注册凭空出现。
* 这个类有一半是拒绝。`OAuthAuthorizationServerProvider` 是**整个**授权服务器，所以它也要求实现授权码流程；一个同时让用户登录的服务器会真正实现那些方法，而这一个只开一扇门。

!!! warning
    SDK 从不解码断言：只有你的部署知道它信任哪个 IdP、那个 IdP 发布哪些密钥，所以 `exchange_identity_assertion` 里的每一步都是承重的。按 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) §3，用 IdP 发布的密钥（它的 JWKS；这里的共享密钥只是演示用的）验证签名，并校验 `iss` 和 `exp`。要求 JWT 头的 `typ` 为 `oauth-id-jag+jwt`，这是 profile 防止别的 JWT 被当作授权许可重放的防护。要求 `aud` 是你自己的 issuer。要求 ID-JAG 的 `client_id` 声明等于处理函数认证过的那个客户端，它的 `resource` 声明指明一个你确实提供的资源。跟踪 `jti` 直到断言的 `exp`，保证它只被接受一次。授予的 scope，尤其是所签发令牌的 `resource`，要取自校验过的 ID-JAG，绝不取自请求：`params.resource` 是客户端随手填的。完整的处理规则见 [Enterprise-Managed Authorization 规范](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization)。

用 `TokenError("invalid_grant", ...)` 拒绝不合格的断言。这个流程里另一个错误码是 `invalid_target`：指明了你不提供的资源的 ID-JAG 就用它拒绝，正是它阻止了这个服务器为别人的资源铸造令牌。授予的 scope 来自 ID-JAG 的 `scope` 声明（没有这个声明的断言同样会被拒绝）；你的实现也许会改为映射用户所属的组。

再注意返回的 `OAuthToken` 里没有什么：刷新令牌。IdP 通过决定是否签发下一个 ID-JAG 来决定这个用户能访问多久。在这里铸造刷新令牌，等于悄悄把这个决定权交了回去。

!!! info
    仍然用 `auth_server_provider=` 内嵌授权服务器的服务器，通过 `AuthSettings(identity_assertion_enabled=True)` 走到同一段代码。**[授权](../run/authorization.md)** 解释了为什么新服务器不应该从那里起步。

!!! check
    把本页的两个文件接在一起，整个授权许可就是一次 `POST /token`：

    ```text
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    assertion=eyJhbGciOiJIUzI1NiIsInR5cCI6Im9hdXRoLWlkLWphZytqd3QifQ...
    client_id=finance-agent
    resource=http://localhost:8001/mcp
    scope=notes:read
    client_secret=finance-agent-secret

    HTTP/1.1 200 OK
    {"access_token": "mcp_...", "token_type": "Bearer", "expires_in": 300, "scope": "notes:read"}
    ```

    没有 `/authorize`，没有 `/register`，没有获取 protected resource metadata。线路上仅有的请求是引出 `401` 的那个、well-known 获取、这次交换，然后就是带着 bearer 的普通 MCP 流量。而你的校验器从 ID-JAG 里读出的 `sub`，正是工具内部 `get_access_token().subject` 报告的值。

### 试一试 {#try-it}

SDK 仓库里的 `examples/stories/identity_assertion/` 就是本页真实跑起来的样子：同一个 `exchange_identity_assertion` 校验器、一个靠它的令牌把关的 MCP 服务器、一个替身 IdP，还有客户端，都在一个自检程序里。`uv run python -m stories.identity_assertion.client --http` 会跑完整个交换，并断言 IdP 指明的用户就是工具看到的用户。

## 回顾 {#recap}

* [SEP-990](https://github.com/modelcontextprotocol/modelcontextprotocol/issues/990) 让企业身份提供方而不是最终用户来决定客户端可以访问哪些 MCP 服务器。IdP 把这个决定签进一个 **ID-JAG**。
* 获取 ID-JAG 是对**你的 IdP** 做的一次 [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) 令牌交换，SDK 不做这一步。向 MCP 授权服务器出示它是 [RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523) 的 `jwt-bearer` 授权许可，这一步的两端 SDK 都做。
* `IdentityAssertionOAuthProvider` 又是一个 `httpx2.Auth`：一个预注册的机密客户端、一个钉死的 `issuer`，加一个 `assertion_provider(audience, resource)` 回调。没有浏览器，没有注册，没有刷新令牌。
* 授权服务器永远不会从资源服务器发现。把 `issuer` 配置成与它的元数据文档提供的字符串完全一致；比较是逐字符的。
* 服务器端是 `identity_assertion_enabled=True` 加 `exchange_identity_assertion`。SDK 认证客户端并为授权许可把关；校验 ID-JAG 完全是你的事，签发的令牌绑定到 ID-JAG 的 `resource`，而不是请求里的。

本页唯一没碰过的一方是 MCP 服务器。它怎么处理你刚铸造的令牌，在 **[授权](../run/authorization.md)** 里早就在做了。
