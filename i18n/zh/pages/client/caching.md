---
translation:
  sections: [9e7b9a1710e5aeba, b74ca4c1d2ddddee, fa8714e61bf90c5a, 04db67a886b7271c, 857690fb8f876800]
  tool: 1
---
# 缓存提示 {#caching-hints}

在 2026-07-28 协议下，服务器为 `tools/list`、`prompts/list`、`resources/list`、`resources/templates/list`、`resources/read` 和 `server/discover` 返回的每个结果都带有两个字段：`ttlMs`，即客户端可以把结果视为新鲜的毫秒数；`cacheScope`，即缓存的结果可以在用户之间共享（`"public"`），还是只属于一个授权上下文（`"private"`）。

服务器本身不缓存任何东西。这些字段只是一种**声明**：“这个工具列表对所有人都一样，一分钟内不会变。”客户端（或挡在你前面的网关）随后可以省掉这次往返。是否遵从这些提示由客户端决定；发出它们是服务器的职责，而 SDK 替你做了这件事。

默认情况下，每个结果都是 `ttlMs: 0, cacheScope: "private"`：立即过期，从不共享。这永远安全，也永远合规。如果你的列表确实稳定、对所有调用者都相同，就在构造时声明：

```python title="server.py" hl_lines="5-8"
--8<-- "docs_src/caching/tutorial001.py"
```

* 这个映射以**方法名**为键，六个可缓存方法是唯一合法的键。参数类型是 `Mapping[CacheableMethod, CacheHint]`，所以编辑器会自动补全键名，并在运行前标出拼写错误；逃过类型检查器的值会在构造时抛出异常。
* 没有提到的方法保留默认值。这个映射是一组覆盖项，不是清单。
* `CacheHint(ttl_ms=5_000)` 没有设置 `scope`，所以它仍是 `"private"`：五秒的新鲜期，按调用者各自计算。作用域和 TTL 是相互独立的决定。
* `"server/discover"` 也是合法的键，因为发现结果和任何列表一样可以缓存。

!!! warning
    `cacheScope: "public"` 意味着**任何人**都可能拿到你缓存的响应。共享网关会毫不犹豫地把一个用户的结果交给另一个用户，哪怕请求经过了认证。只有当结果对每个调用者都完全相同时才标记为 `"public"`，并且绝不要把 `cacheScope` 当作访问控制：它是标签，不是锁。

## 按处理函数覆盖 {#per-handler-override}

在底层 `Server` 上，处理函数手动构建结果，`ttl_ms` / `cache_scope` 只是结果模型上的字段。显式设置了它们的处理函数总是逐字段地优先于构造函数映射：

```python title="server.py" hl_lines="10 16"
--8<-- "docs_src/caching/tutorial002.py"
```

处理函数指定了 `ttl_ms=1_000`，对作用域只字未提。线路上是：`ttlMs: 1000`（处理函数的值，而不是映射里的 `60_000`）和 `cacheScope: "public"`（映射的值，因为处理函数没有设置）。显式优先于配置，配置优先于默认。这条规则按字段生效，所以处理函数可以固定一个字段，把另一个留给服务器范围的策略。

这也是构造函数无法预知的动态情况的出口：一个按用户过滤 `resources/read` 的处理函数，可以在其他方面都是 public 的服务器上为某个 URI 返回 `cache_scope="private"`。

关于分页列表有一点要注意：协议要求同一列表的**每一页 `cacheScope` 相同**。构造函数映射天然满足这一点，因为它按方法而不是按页作键。但自行覆盖作用域的处理函数要自己负责这种一致性：在**每一**页都覆盖，绝不要只在有游标时覆盖，否则第一页和第二页会不一致。

## 客户端看到什么 {#what-the-client-sees}

在 2026-07-28 会话上，`Client` 替你遵从这些提示：它内置了响应缓存，默认开启。带着 `ttlMs` 到达的结果会被存起来，在 TTL 内的相同调用直接由缓存提供，不发生往返。**不**带提示的结果不会被缓存：无提示的结果使用 `CacheConfig.default_ttl_ms`，它默认为 `0`（立即过期），所以什么都没声明的服务器看到的流量和以前一模一样，一次调用对应一次请求。

```python title="client.py" hl_lines="33 35 38"
--8<-- "docs_src/caching/tutorial003.py"
```

四次调用，三次抓取。第二次调用找到了新鲜条目，根本没到服务器；把（注入的）时钟拨过 TTL 让第三次重新抓取；第四次指定了 `cache_mode="refresh"`。这个关键字参数存在于五个缓存动词上（`list_tools`、`list_prompts`、`list_resources`、`list_resource_templates`、`read_resource`）：

* `"use"`（默认）有新鲜条目就返回它，没有就抓取并存储。
* `"refresh"` 从不返回缓存：它抓取并存储结果，替换掉原有缓存。
* `"bypass"` 照常往返但完全不碰缓存：不读，不写。

有一条规则凌驾于 `"use"` 之上：**带 `meta` 的调用总会到达服务器。** 设置了 `meta`（进度令牌、追踪字段）的请求期望产生一次线路请求，所以在 `cache_mode="use"` 下它被当作 `"refresh"` 处理：跳过缓存读取，抓取到的结果仍会替换缓存条目。`"bypass"` 和显式的 `"refresh"` 行为照旧。

要完全关闭缓存，用 `Client(server, cache=None)` 构造：每次调用重新变成一次往返，`cache_mode` 虽然仍被接受，但不起作用。

作用域同样自动遵从：`"private"` 条目按缓存的**分区**（见下文）作键，而 `"public"` 条目可以选择更大范围的共享。并且对于通知点名的那些条目，**通知优先于 TTL**：`list_changed` 通知会驱逐对应的已缓存列表，`resources/updated` 会驱逐恰好存在其 URI 下的已缓存读取结果，不管它们多新鲜。在 2026-07-28 连接上，这些通知通过你用 `client.listen(...)` 打开的 `subscriptions/listen` 流到达，驱逐会在你的观察者看到事件之前完成；详见 **[订阅](subscriptions.md)**。

关于 `resources/updated` 有一点要注意：驱逐只针对精确匹配的 URI。存储契约没有枚举或扫描操作（与参考的 TypeScript 实现相同），所以携带**子**资源 URI 的通知不会驱逐其父资源的已缓存读取结果。如果你的服务器用这种方式通知子资源变化，就用 `cache_mode="refresh"` 重新抓取父资源。

### 配置：`CacheConfig` {#configuring-it-cacheconfig}

```python
from mcp.client import CacheConfig

client = Client("https://api.example.com/mcp", cache=CacheConfig(default_ttl_ms=5_000))
```

* `store`：条目存放的位置。默认是每个客户端一个全新的内存存储；传入你自己的 `ResponseCacheStore` 实现（比如基于 Redis 的）即可在多个客户端或进程之间共享缓存。契约类型（`ResponseCacheStore`、`CacheKey`、`CacheEntry` 以及默认的 `InMemoryResponseCacheStore`）都可以从 `mcp.client` 导入。一次查找最多会对存储发出两次顺序的 `get`（先是 private 分支，然后是 public 分支），所以远程存储的延迟预期要据此估算。自定义存储**必须**显式指定 `partition`。
* `partition`：授权上下文标签，防止在共享存储中把一个主体的 `"private"` 条目提供给另一个主体。
* `target_id`：显式的服务器标识，用于自定义传输方式和进程内服务器（见下文）。
* `default_ttl_ms`：应用于不带 `ttlMs` 提示的结果的 TTL。默认的 `0` 让无提示结果不被缓存。
* `share_public`：跨分区提供服务器声明为 `"public"` 的条目（见下文）。默认关闭。
* `clock`：墙上时钟来源，以纪元秒为单位。像上面的例子那样注入一个，过期测试就不需要 sleep 了。

!!! warning "分区 = 已验证的主体"
    从**已验证的凭证**派生 `partition`，比如经过校验的令牌的 subject。绝不要从请求提供的数据派生，也绝不要从服务器 URL 派生（服务器标识是单独的键维度）。SDK 是一个库，自身不做认证：信任锚点是构造 `CacheConfig` 的一方，也就是部署方，而不是租户。多租户网关为每个已认证主体创建一个 `CacheConfig`。

    分区在 `Client` 的整个生命周期内也是固定的。如果连接的授权上下文在会话中途改变（比如以另一个主体重新认证），缓存不会跟着变；为新的主体构造一个新的 `Client`。

缓存键还携带**服务器的标识**：你连接的 URL 字符串，去掉其中的 `user:pass@` 用户信息，其余逐字节保持原样。不做大小写折叠，不重排查询参数，不清理末尾斜杠。规范化不足只会损失一些共享，而过度规范化可能合并两个租户（`?tenant=a` 对 `?tenant=b`），所以表面上不同的 URL 干脆不共享条目。没有 URL 时（进程内服务器，或 `Transport` 实例），客户端改用每个实例随机生成的标识；设置 `CacheConfig.target_id` 来给服务器命名（使用自定义存储时这是必需的，构造时会报错提示）。标识在进入键材料之前会经过 sha256 哈希，所以查询字符串里带有机密的 URL 永远不会出现在存储键中。你自己也不要记录哈希前的形式。

!!! warning "`share_public` 信任服务器，而且是全集群范围"
    默认情况下，即使是 `"public"` 条目也留在各自的分区内。`share_public=True` 会把服务器标记为 `cacheScope: "public"` 的条目提供给使用该存储的**每一个**分区，代表所有分区信任服务器的分类。如果服务器（因为 bug 或恶意）给按租户区分的数据打上 `"public"`，一个租户的响应就会泄漏给其他租户。这个标志刻意只放在构造函数层面：逐调用的 `cache_mode` 可以收窄缓存，但没有任何逐调用的方式能放宽共享。

### 缓存绝不会做的事 {#what-the-cache-never-does}

* **会话层的调用绕过它。** `client.session.list_tools()` 及同类方法总是发生往返；缓存位于 `Client` 的动词方法上。
* **`server/discover` 不参与。** 发现结果在连接时交付一次，永远不进入响应缓存，即使它带有 `ttlMs`。如果你自己持久化一份来跳过重连探测（[`prior_discover`](../protocol-versions.md#reconnecting-with-prior_discover)），它的新鲜度由你自己记账：`DiscoverResult` 正是为此携带了已解析好的 `ttl_ms` 和 `cache_scope`。
* **续页永不缓存。** 只有不带游标的调用参与。因游标过期而被拒绝的续页确实会**驱逐**已缓存的列表，因为列表在它底下发生了变化。
* **多轮往返（multi-round-trip）读取永不缓存。** 用 `input_responses`/`request_state` 作种子的 `read_resource`，或经过输入轮次才解析完成的读取，永远不进入缓存（规范中的 MUST）。
* **通知驱逐需要通知。** 驱逐的效果取决于传输的投递能力，而现代的进程内路径（`Client(server)` 配合默认的 `mode="auto"`）目前不投递独立通知。
* **驱逐是最终一致的，不是即时的。** 线路路径的通知由派生的任务分发，所以与通知到达竞态的调用可能再被提供一次驱逐前的条目；这个窗口受分发延迟限制，驱逐最终仍会生效。
* **没有 stale-if-error。** 过期条目绝不会因为重新抓取失败而被提供；错误会向上传播。
* **没有提前重新抓取。** 已存储的条目一直提供到 TTL 过期，之后的下一次调用承担往返开销；没有任何后台刷新。
* **没有合并。** 两个并发的相同调用就是两次抓取。
* **TTL 不超过 24 小时。** 更大的 `ttlMs`，无论是服务器发送的还是配置的，存储时都会被钳制（`mcp.client.caching.MAX_TTL_MS`），从而限制任何条目（无论提示多慷慨）能被提供多久。
* 在**共享存储**上，客户端之间会相互竞态。当驱逐赶在进行中的抓取之前发生时，每个客户端会丢弃自己的写入，但**同租**的客户端仍可能把一个被它从未见过的驱逐移除的条目写回去；而这套竞态记账本身也有上限：跟踪的键超过 4096 个后，最旧的键的保护先被丢弃。这两个窗口都是可接受的，并由上面的 TTL 上限兜底关闭。
* **不跨协议时代提供。** 条目按协商的协议版本划定范围：在共享的持久存储上，会话绝不会提供在另一个协商版本下写入的条目（同一份列表在不同时代确实不同，因为 SDK 会为旧会话剥离 2026 的字段）。驱逐同样只触及当前时代的条目；其他时代的条目只是随 TTL 自然过期。

### 自己读取提示 {#reading-the-hints-yourself}

这些提示也是每个可缓存结果上的普通字段（`result.ttl_ms` 和 `result.cache_scope`，已解析好），方便你在内置缓存之上（或代替它）叠加自己的记账逻辑。

面对**旧服务器**（2026 之前的协议），这些字段在线路上根本不存在，模型显示的是保守的默认值：`ttl_ms == 0` 和 `cache_scope == "private"`，过期且不共享，对于什么都没声明的服务器这正是正确的假设。缓存对旧会话一视同仁：在那里从不参考提示（不管线路上出现什么键），只有 `default_ttl_ms` 生效，而它的默认值 `0` 什么都不缓存，所以 2026 之前的连接行为和缓存出现之前完全一样。如果需要区分“服务器说了 0”和“服务器什么都没说”，检查 `"ttl_ms" in result.model_fields_set`：只有字段确实到达时它才会被设置。

## 旧客户端 {#older-clients}

使用 2026 之前协议版本的客户端永远看不到这两个字段；SDK 会在序列化时为这些连接剥离它们。提示只需配置一次，没有任何版本相关的代码要写。

## 回顾 {#recap}

* 六个方法携带 `ttlMs`/`cacheScope`；SDK 默认它们为 `0`/`"private"`，过期且不共享，永远安全。
* 构造时的 `cache_hints={method: CacheHint(...)}`（`MCPServer` 和 `Server` 都支持）按方法设置服务器范围的值。
* 在结果上设置了这些字段的处理函数会逐字段覆盖映射。
* `"public"` 是一个承诺：结果对每个调用者都相同。它不是访问控制。
* `Client` 自动遵从提示：它的响应缓存默认开启，提供新鲜条目而不是重新抓取，对不提供提示的服务器（或会话）什么都不缓存。
* 逐调用地，`cache_mode="refresh"` 重新抓取，`"bypass"` 跳过缓存；构造时 `cache=None` 则完全关闭它。
