---
translation:
  sections: [478fd619e5f90ef8, aef094a00e44e248, bab8cbf3449fa7e9, df1809b15a58335b, 5f9d8c2336ed0239, f54974398e43ddef, b24443dd78584870]
  tool: 1
---
# 协议版本 {#protocol-versions}

MCP 有两个时代。

在 2026-07-28 之前发布的服务器，每个连接都以 **`initialize` 握手**开场：客户端提出一个版本，服务器回应，客户端确认，这一切都发生在第一个真正有用的请求之前。**2026-07-28** 的服务器去掉了握手。客户端发送一次 **`server/discover`** 探测，服务器用一个结果一次性回答全部内容。

你几乎不需要关心这些，因为 `Client` 会替你协商。本页讲的是控制这一行为的唯一一个构造参数 `mode=`，以及需要改动它的三种情形。

## `mode="auto"` {#modeauto}

```python title="client.py" hl_lines="14-15"
--8<-- "docs_src/protocol_versions/tutorial001.py"
```

没有传 `mode`，所以用的是默认值：`"auto"`。进入 `async with` 时，会以本 SDK 支持的最新版本发送一次 `server/discover` 探测。然后：

* **新版服务器**会回答它。客户端采纳结果。一次往返，完事。
* **旧版服务器**从没听说过 `server/discover`，返回一个错误。客户端回退到经典的 `initialize` 握手，接受握手协商出的结果。

无论哪种情况，结束时连接都已建立，`client.protocol_version` 会告诉你走的是哪条路：

```text
2026-07-28
```

整个功能就这些。一个 `Client`，任意时代的服务器，代码里不需要分支。

!!! info
    `MCPServer` 在每种传输方式上都会回答 `server/discover`——内存、stdio、Streamable HTTP——所以连接你自己的服务器时，`auto` 总是落在 `2026-07-28`。回退只会在面对真正的 2026 年之前的服务器时触发，而那正是你需要它的时候。

## `mode="legacy"` {#modelegacy}

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial002.py"
```

`mode="legacy"` 从不探测。它执行 `initialize` 握手，打开的连接和 2026 年之前的客户端一样。

```text
2025-11-25
```

同一个服务器。它完全能讲 `2026-07-28`；是你告诉客户端不要去问。

**推送式**功能需要这个模式。

服务器发起的请求，就是服务器调用**你**：`ctx.elicit(...)` 在你的用户面前弹出一个表单，采样（sampling）在工具调用中途向你的模型请求补全。这条通道只存在于握手时代的会话上。

到了 2026-07-28，它就没有了。服务器把问题**返回**给你，你带着答案重试这次调用（**[多轮往返（multi-round-trip）请求](handlers/multi-round-trip.md)**）。

`mode="auto"` 只有在服务器旧到别无选择时才会给你握手。`mode="legacy"` 则保证有握手。只要给 `Client(...)` 传了 `sampling_callback`、希望以请求方式驱动的 `elicitation_callback`，或者 `message_handler`，就用它。**[客户端回调](client/callbacks.md)** 会逐一讲解。

## 固定版本 {#pinning-a-version}

`mode` 也接受一个新版协议版本字符串。目前这个集合正好是 `["2026-07-28"]`。

```python title="client.py" hl_lines="14"
--8<-- "docs_src/protocol_versions/tutorial003.py"
```

固定版本**什么都不**发送。没有探测，没有握手。客户端在本地采纳 `2026-07-28`，`async with` 一返回连接就可用。

固定版本是**你**做出的承诺：你已经知道服务器讲这个版本。客户端不会检查。

!!! check
    固定版本不是发现。打印 `client.server_info`，代价一目了然：

    ```text
    None
    ```

    客户端从没问过服务器它是谁，所以 `server_info` 是 `None`。`client.server_capabilities` 也是一样：每项能力都是 `None`。工具调用照常工作（协议不需要这些信息）；而那些读取 `server_capabilities` 来决定提供什么的代码就不行了。

    下一节就是解决办法。

只有新版版本可以固定。握手时代的字符串在构造时就会被拒绝，在任何 I/O 之前，错误信息会告诉你该怎么写：

```text
ValueError: mode must be 'legacy', 'auto', or one of ['2026-07-28']; got '2025-06-18' ('2025-06-18' is a handshake-era version; use mode='legacy')
```

## 用 `prior_discover` 重连 {#reconnecting-with-prior_discover}

探测很便宜，但它仍然是每次重连都要付出的一次往返，而答案几乎从不改变。

所以把它存下来。一次 `auto` 连接之后，`client.session.discover_result` 保存着服务器发来的那个 `DiscoverResult` 原样：它的 `supported_versions`、它的 `capabilities`、它的 `instructions`，以及服务器写进结果 `_meta` 里的身份信息。下次把它作为 `prior_discover=` 传回去：

```python title="client.py" hl_lines="15 17"
--8<-- "docs_src/protocol_versions/tutorial004.py"
```

```text
2026-07-28
Bookshop
```

第二次连接的协商往返为**零**，却依然清楚地知道对方是谁。这才是固定模式的正确用法：`mode=` 指定版本，`prior_discover=` 提供身份。✨

`DiscoverResult` 是一个 Pydantic 模型。`saved.model_dump_json()` 可以写进文件或缓存；`DiscoverResult.model_validate_json(...)` 在下一个进程里把它取回来。

!!! tip
    `prior_discover=` 只有在 `mode` 是版本固定时才起作用。在 `"auto"` 下客户端照样会探测服务器，在 `"legacy"` 下它会被忽略。

## 四种模式 {#the-four-modes}

| 你写的 | 协商流量 | 你得到的 |
| --- | --- | --- |
| `Client(target)` | 一次 `server/discover` 探测；失败则执行 `initialize` 握手 | 双方都支持的最新版本，不论哪个时代 |
| `Client(target, mode="legacy")` | `initialize` 握手 | 一个握手时代的版本；服务器发起的请求可用 |
| `Client(target, mode="2026-07-28")` | 无 | 该版本，已固定，`server_info` 为 `None` |
| `Client(target, mode="2026-07-28", prior_discover=saved)` | 无 | 该版本，已固定，**外加**你上次保存的身份 |

## 回顾 {#recap}

* MCP 有一个握手时代（到 `2025-11-25` 为止，`initialize` 握手）和一个新时代（`2026-07-28`，`server/discover`）。`Client` 在两者之间架桥。
* `mode="auto"` 是默认值：先探测，再回退。除非另外三行之一说的是你，否则不用动它。
* `client.protocol_version` 永远能回答“我得到的是什么？”。
* `mode="legacy"` 强制握手。服务器发起的请求需要它：采样、推送式征询（elicitation）、`message_handler`。
* 版本固定（`mode="2026-07-28"`）完全不发送协商流量，代价是 `client.server_info` 为 `None`。
* `prior_discover=` 把这个代价补回来：保存 `client.session.discover_result`，用它重连，两者兼得。

新版连接没有推送通道，那么 2026 的服务器在调用中途怎么向你提问？它把问题返回：**[多轮往返请求](handlers/multi-round-trip.md)**。
