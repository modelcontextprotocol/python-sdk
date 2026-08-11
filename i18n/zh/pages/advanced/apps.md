---
translation:
  sections: [0355618e5f4d5fe4, 1821eaf50f2d0b64, 82e0b28ebd3abf5a, 8ac39614c094f2d0, dab6ff945501ab2a, bd5565c3b2d4f959, 96819ce3d63a0487]
  tool: 1
---
# MCP Apps {#mcp-apps}

**MCP App** 是带界面的工具：除了返回数据，这个工具还指向一个 HTML 文档，由宿主渲染成可交互的界面。

两个部分，永远是两个部分：

1. **一个工具**，负责干活并返回数据，和其他工具一样。
2. **一个 `ui://` 资源**，包含宿主为它展示的 HTML。

工具通过 `_meta.ui.resourceUri` 引用这个资源。宿主用 `resources/read` 获取它，在**沙箱化的 iframe** 里渲染，再通过 `postMessage` 把工具的结果推送进 iframe。你的服务器从不收发任何 `ui/*` 消息：那些流量只在宿主和 iframe 之间往来。你提供一个工具和一份 HTML 文档，展示的事由宿主包办。

SDK 把它作为内置的 `Apps` 扩展（`io.modelcontextprotocol/ui`）提供。如果还不熟悉[扩展](extensions.md)，先浏览一下那一页。一分钟就够，然后回来。

## 一个带界面的时钟 {#a-clock-with-a-face}

```python title="server.py" hl_lines="19 22 30 32"
--8<-- "docs_src/apps/tutorial001.py"
```

四步：

* `Apps()`：一个实例容纳所有绑定 UI 的工具及其资源。
* `@apps.tool(resource_uri="ui://clock/app.html")`：一个普通工具，外加 `_meta.ui.resourceUri` 标记。`@mcp.tool()` 接受的所有参数（name、title、description……）都会原样传递。
* `apps.add_html_resource("ui://clock/app.html", CLOCK_HTML)`：与之对应的资源，以 `text/html;profile=mcp-app` 提供。正是这个 MIME 类型告诉宿主“这是一个 app，渲染它”。
* `MCPServer("clock", extensions=[apps])`：选择启用。服务器现在会在 `capabilities.extensions` 下声明 `io.modelcontextprotocol/ui`。

HTML 本身监听宿主的 `postMessage` 并显示结果。真正的应用请在 HTML 里使用官方的 [`@modelcontextprotocol/ext-apps`](https://github.com/modelcontextprotocol/ext-apps) 浏览器 SDK。它提供 `ontoolresult`、`callServerTool`、`getHostContext` 和 `onhostcontextchanged`，不用再处理原始的 message 事件。

## 优雅降级 {#graceful-degradation}

不是每个客户端都能渲染 app。这对你意味着什么，规范说得很直白：

> 即使有 UI 可用，工具也**必须**返回有意义的 `content` 数组。

模型读的是 `content`；iframe 是给人看的。支持 UI 的宿主照样会把文本结果交给模型，而纯文本客户端**只**拿到那部分。所以标准模式是一个工具、两种回答。再看一遍 `get_time`：

```python title="server.py" hl_lines="23-27"
--8<-- "docs_src/apps/tutorial001.py"
```

只有当客户端声明了 `io.modelcontextprotocol/ui` 扩展，**并且**在其 `mimeTypes` 设置里列出了 `text/html;profile=mcp-app` 时，`client_supports_apps(ctx)` 才为 `True`。这个字段是必填的，省略它的客户端不算数。同一文件里的 `main()` 声明的正是这些：协商中客户端的那一半，于是富结果就返回了。

!!! warning
    绝不要把 `"[Rendered UI]"` 这样的占位符当作唯一的内容返回。如果回退文本没用，这个工具对所有纯文本客户端乃至模型本身就都没用。把那句话写出来。

## 给 iframe 上锁 {#locking-the-iframe-down}

安全相关的元数据放在资源一侧：iframe 可以加载什么、想要哪些浏览器权限、希望被怎样嵌入：

```python title="server.py" hl_lines="9 19-22"
--8<-- "docs_src/apps/tutorial002.py"
```

`csp` 和 `permissions` 是**向宿主提出的请求**，不是服务器的行为。宿主据此构建 iframe 的 Content-Security-Policy 和 Permissions-Policy，也可以拒绝。在 JS 里做特性检测，不要假定已经获准。

`ResourceCsp` 逐字段说明（Python 名、线路上的键、宿主拿它做什么）：

| Python | 线路（`_meta.ui.csp`） | 控制 |
|---|---|---|
| `connect_domains` | `connectDomains` | `connect-src`：`fetch`/XHR 可以访问哪里 |
| `resource_domains` | `resourceDomains` | `img-src`、`style-src`……：静态资源 |
| `frame_domains` | `frameDomains` | `frame-src`：嵌套的 iframe |
| `base_uri_domains` | `baseUriDomains` | `base-uri`：`<base>` 可以指向哪里 |

`ResourcePermissions`：每个字段为 iframe 请求一项浏览器权限。

| Python | 线路（`_meta.ui.permissions`） |
|---|---|
| `camera` | `camera` |
| `microphone` | `microphone` |
| `geolocation` | `geolocation` |
| `clipboard_write` | `clipboardWrite` |

!!! note
    CSP 和权限放在**资源**上，绝不放在工具上。规范的工具元数据里没有它们的位置，放在那里宿主也会忽略。SDK 让这个错误根本无从表达：`@apps.tool()` 压根没有 `csp` 参数。

### 可见性 {#visibility}

工具上的 `visibility=["app"]` 表示“这是给 iframe 用的，不是给模型用的”：

* `"model"`：模型可以调用它。
* `"app"`：iframe 可以调用它（通过 `callServerTool`）。
* 省略：两者都可以，这也是默认值。

过滤是**宿主**的事。服务器在 `tools/list` 里照常列出仅限 app 的工具；宿主负责对模型隐藏它们。不要在服务器端过滤。

## SDK 强制执行的规则 {#the-rules-the-sdk-enforces}

这些都会在启动时失败，而不是在生产环境里：

* 不是 `ui://...` 的 `resource_uri` 或资源 URI，在装饰/注册时抛出 `ValueError`。
* 绑定到某个 URI 却**没有对应的已注册资源**的工具，在 `MCPServer(extensions=[apps])` 消费这个扩展时抛出 `ValueError`。一个声明了 HTML、却在 `resources/read` 上 404 的工具属于配置错误，所以直接拒绝构造。
* 在 `@apps.tool()` 上传入 `meta={"ui": ...}` 会抛出 `ValueError`。`_meta["ui"]` 归装饰器管；用 `resource_uri=` 和 `visibility=` 来表达。其他 `meta=` 键可以正常一并合并。

TypeScript 的 ext-apps SDK 和 FastMCP 目前都不检查这些；我们宁愿你先于宿主发现问题。

## 内联 HTML 之外 {#beyond-inline-html}

`add_html_resource` 覆盖常见情况：一段 HTML 字符串。其他情况，比如磁盘上的 HTML 或生成的内容，自己构建资源再交给它：

```python title="server.py" hl_lines="12 18"
--8<-- "docs_src/apps/tutorial003.py"
```

资源没有显式设置 MIME 类型时，`add_resource` 会填上 `text/html;profile=mcp-app`；显式设置了不匹配的类型则会拒绝：用其他任何 MIME 类型的 `ui://` 资源，没有宿主会渲染。

!!! tip
    目标宿主是 GA 之前的版本，还在读取已弃用的扁平键 `_meta["ui/resourceUri"]`？自己合并进去：`@apps.tool(resource_uri="ui://x", meta={"ui/resourceUri": "ui://x"})`。嵌套的 `ui` 对象才是规范规定的形态；扁平键正在退出。

## 运行看看 {#see-it-run}

`examples/stories/` 里的 `apps` story 就是本页的可运行版本，由一对程序组成：一个带有绑定 UI 的时钟工具的服务器，和一个协商 Apps、读取工具的 `_meta.ui.resourceUri`、获取 HTML 并调用工具的客户端。

```bash
uv run python -m stories.apps.client
```
