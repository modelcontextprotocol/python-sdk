---
translation:
  sections: [4a7033e1ed8ad602, 55dcbfff0c6271bf, 101ef9d14bf4ec46, 4b6c4a845438abc7, f98b46bafbee4acd]
  tool: 1
---
# URI 模板与路径安全 {#uri-templates-and-path-safety}

本页是 [`@mcp.resource`](resources.md) 所接受的 URI 模板语法的参考，也涵盖 SDK 对提取出的值应用的路径安全策略。想了解资源是什么、什么时候该用，请先看 **[资源](resources.md)**；本页假设你已经熟悉如何声明资源，想要的是完整的运算符集合、安全方面的配置项，或者底层的接线方式。

模板语法是 [RFC 6570](https://datatracker.ietf.org/doc/html/rfc6570)。SDK 支持其中一个子集，专为匹配传入的 `resources/read` URI 而选，另外还加了一层安全检查，会拒绝那些会解析到你打算提供的目录之外的值。协议层面的细节（消息格式、生命周期、分页）见 [MCP 资源规范](https://modelcontextprotocol.io/specification/latest/server/resources)。

## 完整的运算符集合 {#the-full-operator-set}

普通占位符 `{user_id}` 就是 **[资源](resources.md)** 一页介绍过的那种。除此之外还有四种运算符形式；下面把它们放在同一个服务器上，方便并排对照：

```python title="server.py" hl_lines="16-17 22-23 28-29 34-35 40-41"
--8<-- "docs_src/uri_templates/tutorial001.py"
```

每个高亮的装饰器都是切分 URI 的一种不同方式。下面各节从上到下依次讲解。

### 简单展开：`{name}` {#simple-expansion-name}

`books://{isbn}` 是最普通、最常用的形式。占位符映射到 `isbn` 参数，所以客户端读取 `books://978-0441172719` 时会调用 `get_book("978-0441172719")`。

普通的 `{name}` 在第一个 `/` 处停止。`books://978/extra` 不匹配，因为 `978` 后面的斜杠终止了捕获，`/extra` 就多出来了。

### 类型转换 {#type-conversion}

提取出的值都是字符串，但可以声明更具体的类型，SDK 会负责转换。`orders://{order_id}` 对应的函数参数是 `order_id: int`，所以读取 `orders://12345` 会调用 `get_order(12345)`，而不是 `get_order("12345")`。处理函数直接对它做算术运算（`order_id + 1`），不需要强制转换。

### 多段路径：`{+name}` {#multi-segment-paths-name}

要捕获包含斜杠的值，用 `{+name}`。以 `manuals://{+path}` 为例：

* `manuals://returns.md` 得到 `path = "returns.md"`
* `manuals://printing/setup.md` 得到 `path = "printing/setup.md"`

只要值是层级结构的，就用 `{+name}`：文件系统路径、嵌套对象的键、你正在代理的 URL 路径。

### 查询参数：`{?a,b,c}` {#query-parameters-abc}

`reviews://{isbn}{?limit,sort}` 把 `limit` 和 `sort` 放在 `?` 之后。路径确定读**哪一本**书；查询参数调整**怎么**读它。

查询参数的匹配是宽松的：顺序无所谓，多余的会被忽略，省略的则落到函数的默认值上。所以 `reviews://978-0441172719` 使用 `limit=10, sort="newest"`，而 `reviews://978-0441172719?sort=top` 只覆盖 `sort`。

### 把路径段作为列表：`{/name*}` {#path-segments-as-a-list-name}

如果想让每个路径段成为列表里独立的一项，而不是一个带斜杠的字符串，用 `{/name*}`。以 `shelves://browse{/path*}` 为例，客户端读取 `shelves://browse/fiction/sci-fi` 会调用 `browse_shelf(["fiction", "sci-fi"])`。

### 模板速查 {#template-reference}

最常见的模式：

| 模式         | 示例输入              | 得到的值                |
|--------------|-----------------------|-------------------------|
| `{name}`     | `alice`               | `"alice"`               |
| `{name}`     | `docs/intro.md`       | **不匹配**（在 `/` 处停止） |
| `{+path}`    | `docs/intro.md`       | `"docs/intro.md"`       |
| `{.ext}`     | `.json`               | `"json"`                |
| `{/segment}` | `/v2`                 | `"v2"`                  |
| `{?key}`     | `?key=value`          | `"value"`               |
| `{?a,b}`     | `?a=1&b=2`            | `"1"`, `"2"`            |
| `{/path*}`   | `/a/b/c`              | `["a", "b", "c"]`       |

### 解析器会拒绝什么 {#what-the-parser-rejects}

有几种模板形式会在一开始就被拦下，而不是等到第一个请求时才失败。`@mcp.resource` 在装饰器运行时就解析模板，所以这些问题都不会进入运行中的服务器。

`UriTemplate.parse()` 在以下情况抛出 `InvalidUriTemplate`：

* **两个变量之间什么都没有。** `manuals://{+path}{ext}` 会被拒绝：匹配时无法判断 `path` 在哪里结束、`ext` 从哪里开始。在它们之间放一个字面量（`manuals://{+path}/{ext}`），或者使用自带分隔符的运算符。`manuals://{+path}{.ext}` 可以接受，因为 `{.ext}` 自己提供了 `.`。
* **不止一个多段变量。** 每个模板最多只能有一个 `{+var}`、`{#var}` 或展开变量（`{/var*}`、`{.var*}`、`{;var*}`）。两个就有本质上的歧义：没有合理的办法决定多出来的段该归哪一个。
* **常见的语法错误**：花括号没闭合、变量名重复使用，或者用了 SDK 不支持的 RFC 6570 特性，比如 `{var:3}` 前缀修饰符或 `{?vars*}` 查询展开。

此外，如果处理函数的某个参数绑定到模板末尾 `{?...}`/`{&...}` 段里的查询变量，却没有 Python 默认值，`@mcp.resource` 会抛出 `ValueError`。这些变量的匹配是宽松的（客户端可以省略其中任何一个），所以没有默认值的参数只会在第一个省略它的请求上以一个含糊的内部错误暴露出来。上面服务器里的 `reviews://{isbn}{?limit,sort}` 就是规范的写法：`limit` 和 `sort` 都带默认值。

## 安全 {#security}

模板参数来自客户端。如果不加检查就流入文件系统或数据库操作，像 `../../etc/passwd` 这样的值就可能解析到你原本打算提供的目录之外。

### SDK 默认检查什么 {#what-the-sdk-checks-by-default}

在处理函数运行之前，SDK 会拒绝任何符合以下情况的参数：

* 通过 `..` 路径组件逃出起始目录
* 看起来像绝对路径（`/etc/passwd`、`C:\Windows`）或 Windows 盘符相对路径（`C:foo`）。盘符相对值和 `x:y` 这样带命名空间的标识符作为字符串无法区分，所以任何由单个字母加冒号构成的值默认都会被拒绝；如果该参数确实会合法地收到这类值，就把它设为豁免
* 包含空字节（`\x00`）

`..` 检查是基于路径组件的，不是子串扫描。`v1.0..v2.0` 或 `HEAD~3..HEAD` 这样的值能通过，因为其中的 `..` 并不是独立的路径段。

这些检查作用于解码后的值，所以无论路径穿越在 URI 里是怎么编码的都能抓到（`../etc`、`..%2Fetc`、`%2E%2E/etc`、`..%5Cetc`、`%00` 全都会被拦下）。

!!! check
    从上面的服务器读取 `manuals://../etc/passwd`，请求会被直接拒绝：模板匹配在第一次失败时就停止，所以不会再把后面（可能更宽松）的模板当作后备去尝试。客户端看到的是 `-32602` “Unknown resource” 错误，和一个完全不匹配任何模板的 URI 一样，而 `read_manual` 根本不会运行。

### 文件系统处理函数：使用 safe_join {#filesystem-handlers-use-safe_join}

内置检查能拦住常见情况，但无从知道你的沙箱边界在哪。访问文件系统时，用 `safe_join` 解析路径并确认它仍在基础目录之内：

```python title="server.py" hl_lines="4 14"
--8<-- "docs_src/uri_templates/tutorial002.py"
```

`safe_join` 能抓到符号链接逃逸、`..` 序列，以及简单字符串检查会漏掉的绝对路径花招。如果解析后的路径逃出了 `DOCS_ROOT`，它会抛出 `PathEscapeError`，在客户端那边表现为 `ResourceError`。

### 默认设置碍事的时候 {#when-the-defaults-get-in-the-way}

有时这些检查会挡住合法的值。一个书目导入工具可能本来就要接收绝对路径，或者某个参数是 `../sibling` 这样的相对引用，处理函数会在不碰文件系统的前提下安全地解释它。可以豁免那个参数，或者放宽整个服务器的策略：

```python title="server.py" hl_lines="9 16-19"
--8<-- "docs_src/uri_templates/tutorial003.py"
```

* 装饰器上的 `security=ResourceSecurity(exempt_params={"source"})` 只对这一个资源的这一个参数跳过检查。服务器的其余部分保持默认策略。
* `MCPServer` 构造函数上的 `resource_security=` 为每个资源设置默认值。这里的 `relaxed` 把 `..` 检查整个关掉了。

可配置的检查项：

| 设置                    | 默认值  | 作用                                |
|-------------------------|---------|-------------------------------------|
| `reject_path_traversal` | `True`  | 拒绝逃出起始目录的 `..` 序列 |
| `reject_absolute_paths` | `True`  | 拒绝 `/foo`、`C:\foo`、UNC 路径和盘符相对的 `C:foo`（也会拦下 `x:y`） |
| `reject_null_bytes`     | `True`  | 拒绝包含 `\x00` 的值                |
| `exempt_params`         | 空      | 要跳过检查的参数名                  |

这些检查只是启发式的预过滤；访问文件系统时，`safe_join` 仍然是真正的隔离边界。

!!! tip
    如果处理函数无法完成请求（文件不存在、id 未知），就抛出异常。SDK 会把它变成错误响应。协议错误和工具错误的区别见 **[处理错误](handling-errors.md)**。

## 底层 Server 上的资源 {#resources-on-the-low-level-server}

如果你是基于底层 `Server` 构建（见 **[底层 Server](../advanced/low-level-server.md)**），就要直接为 `resources/list` 和 `resources/read` 这两个协议方法注册处理函数。没有装饰器；协议类型由你自己返回。

### 静态资源 {#static-resources}

对于固定的 URI，维护一个注册表，按精确匹配分发：

```python title="server.py" hl_lines="17 21 27"
--8<-- "docs_src/uri_templates/tutorial004.py"
```

列表处理函数告诉客户端有哪些可用；读取处理函数提供内容。先查注册表，如果有模板（见下）就接着落到模板上，其他情况一律抛异常。

### 模板 {#templates}

`MCPServer` 使用的模板引擎位于 `mcp.shared.uri_template`，可以独立使用。解析和匹配完全一样；路由和安全策略由你自己接上。

```python title="server.py" hl_lines="13-16 22-25 29 33 45"
--8<-- "docs_src/uri_templates/tutorial005.py"
```

高亮的几行里发生了三件事：

* **解析一次，每个请求匹配一次。** `UriTemplate.parse()` 构建模板；`template.match(uri)` 以 `dict` 形式返回提取出的变量，URI 不符合时返回 `None`。URL 解码在 `match()` 内部完成；解码后的值原样返回，不做路径安全校验。值都是字符串：自己转换（`int(matched["id"])`、`Path(matched["path"])`）。
* **自己应用安全检查。** `MCPServer` 默认运行的 `..` 和绝对路径检查位于 `mcp.shared.path_security`。`read_manual_safely` 在碰 `MANUALS` 之前调用它们。如果某个参数不是文件系统路径（ISBN、搜索查询），就跳过对该值的检查：策略由你按处理函数逐个控制，而不是通过配置对象。
* **从同一来源列出模板。** 客户端通过 `resources/templates/list` 发现模板。`str(template)` 返回原始模板字符串，所以列表和匹配器共用同一份事实来源。

## 回顾 {#recap}

* `{name}` 匹配一段；`{+name}` 保留斜杠；`{?a,b}` 从查询字符串取值；`{/name*}` 把各段拆成列表。
* 两个变量之间什么都没有，或者出现第二个多段变量，都会在解析时被拒绝。绑定到末尾 `{?...}`/`{&...}` 查询变量的参数必须声明 Python 默认值。
* 给参数加上类型注解（`order_id: int`），SDK 就会转换。
* 默认安全策略在处理函数运行之前拒绝 `..`、绝对路径和空字节；用 `security=ResourceSecurity(...)` 按资源覆盖，或用 `resource_security=` 在整个服务器范围内覆盖。
* 访问文件系统时，`safe_join` 是隔离边界。
* 在底层 `Server` 上，用 `UriTemplate.parse()` 解析，用 `.match()` 匹配，并自己应用 `mcp.shared.path_security`。
