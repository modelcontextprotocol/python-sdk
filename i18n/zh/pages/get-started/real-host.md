---
translation:
  sections: [3c4f2f06b4e978b6, 22520eecae3d1961, f4e1709db18d635a, 2eb57992049671d9, 1ba83e9af37cc1b4, 4822586344b08d9e, 1c93afef72478992, b6b448f9eddd51dc, fe55370fd931815b]
  tool: 1
---
# 连接到真实的宿主 {#connect-to-a-real-host}

**宿主** 是你的服务器最终所处的应用程序：Claude Desktop、Claude Code、IDE。用户与之对话的是宿主。在宿主内部，一个 MCP **客户端** 把你的服务器作为子进程启动，并通过该进程的 stdin 和 stdout 与它通信。

也就是说，连接到宿主只需要做一件事：告诉它 **启动服务器的命令**。本页的所有内容（两条 CLI 命令、三个 JSON 文件）都只是放置同一条命令的不同位置。

## 一个服务器，所有宿主 {#one-server-every-host}

```python title="server.py" hl_lines="3 33-34"
--8<-- "docs_src/real_host/tutorial001.py"
```

两个工具加一个资源，全在一个文件里。关于这个文件，有三点对下面每个宿主都很重要：

* 不带参数的 `mcp.run()` 启动的是 **stdio** 服务器：它会阻塞，从 stdin 读取协议消息，再把消息写到 stdout。本页每个宿主用的都是这种传输方式。宿主把你的文件作为子进程启动，并掌管这两个管道，所以连接从来都只是“把命令告诉它”这一件事。你永远不用选端口，也没有任何东西在端口上监听。
* `run()` 放在 `if __name__ == "__main__":` 之下。下文的所有方式都是 **导入** 这个文件而不是执行它，所以不加这层保护的 `run()` 会在模块被任何东西加载的那一刻就启动服务器。
* 服务器对象是一个名为 `mcp` 的模块级全局变量。这是 `mcp run` 要找的名字（`server` 和 `app` 也行）。如果起了别的名字，就得显式指定：`mcp run server.py:bookshop`。

这是本页最后一行 Python。从这里往下全是宿主配置。

## 启动命令 {#the-launch-command}

下面每个宿主拿到的都是同一条命令：

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

所有宿主共用一条命令，是因为 `uv run --with` 会当场把 SDK 解析进一个全新的环境：在任何目录下都能用，既不需要项目，也不需要激活虚拟环境。这一点在这里比在别处都更要紧，因为宿主是从 **它自己的** 工作目录、带着几乎为空的环境启动你的服务器，而不是从你的 shell。

它也是 `mcp install` 替你写进 Claude Desktop 配置的那条命令（见下文），所以手敲的和工具生成的是一致的，差别只在工具额外加上的精确版本锁定。

!!! tip "如果宿主找不到 `uv`"
    宿主启动你的服务器时只带一个极简的 `PATH`，`uv` 可能不在其中。把不带路径的 `uv` 换成 `which uv`（macOS/Linux）或 `where uv`（Windows）给出的绝对路径。`mcp install` 写入的正是这个。

!!! note "本页讲的是本地场景"
    这里的一切都是在宿主所在的那台机器上运行你的服务器：宿主通过 stdio 启动你的文件。对个人工具或单机工具来说，这样做完全合适。要把服务器交给 **没有** 你这个文件的人，给出去的是 **URL** 而不是命令：同一个 `mcp` 对象，通过 Streamable HTTP 提供服务。**[运行服务器](../run/index.md)** 用一张表讲清这个决策，**[部署与扩展](../run/deploy.md)** 则是从那里走到真实主机名的路线。

    而且宿主不过是内置了 MCP 客户端的应用程序，所以你自己的 Python 也能扮演宿主的角色：**[客户端传输方式](../client/transports.md)** 用 `stdio_client(...)` 把同一个文件作为子进程启动，**[测试](testing.md)** 则一个进程都不起，直接在内存中连接它。

## Claude Desktop {#claude-desktop}

唯一一个 SDK 能替你配置的宿主：

```bash
uv run mcp install server.py
```

就这样。`mcp install` 导入该文件以读取服务器的名字，找到 Claude Desktop 的配置文件，然后把启动命令写进去。过程中它会把你的路径转换成绝对路径，省得你自己动手。

这里没有什么玄机。它写入的条目是这样的：

```json
{
  "mcpServers": {
    "Bookshop": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--frozen",
        "--with",
        "mcp[cli]==2.0.0",
        "mcp",
        "run",
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

这就是上一节的启动命令，外加三样东西：`uv` 的绝对路径、`--frozen`（让 `uv` 永远不会改写它碰巧挨着的锁文件），以及对你已安装的 `mcp` 版本的精确锁定。它最终写进 `claude_desktop_config.json`，该文件位于：

* **macOS**：`~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows**：`%APPDATA%\Claude\claude_desktop_config.json`

这个文件可以手写。`mcp install` 存在的意义，就是让你手写时不会犯那个经典错误（相对路径）。

完全退出 Claude Desktop（不只是关掉窗口），再重新打开。

!!! warning
    如果 Claude Desktop 的配置 **目录** 还不存在，`mcp install` 会失败并报 `Claude app not found`。安装 Claude Desktop 并运行一次：目录正是这一步创建的。

!!! tip
    Claude Desktop 在它自己的进程中启动你的服务器，所以那里没有你 shell 里的环境变量。`uv run mcp install server.py -v API_KEY=abc123`（或 `-f .env`）会把它们记到条目的 `env` 字段里。`--name` 用来覆盖条目名；默认取服务器的 `name`。

## Claude Code {#claude-code}

没有文件要编辑。用 `claude` CLI 注册服务器；`--` 之后的所有内容就是启动命令。

```bash
claude mcp add bookshop -- uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

在 Claude Code 会话中运行 `/mcp`，确认 `bookshop` 已连接，且它的工具已列出。

## Cursor {#cursor}

在项目根目录创建 `.cursor/mcp.json`。

```json
{
  "mcpServers": {
    "bookshop": {
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

同样的 `command` 加 `args`，放在 Claude Desktop 也在用的 `mcpServers` 键下。服务器会出现在 Cursor 的 MCP 设置里，两个工具都已列出。

## VS Code {#vs-code}

在项目根目录创建 `.vscode/mcp.json`。

```json
{
  "servers": {
    "bookshop": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp[cli]", "mcp", "run", "/absolute/path/to/server.py"]
    }
  }
}
```

和 Cursor 的文件有两处不同，也仅此两处：外层键是 `servers` 而不是 `mcpServers`，而且每个条目都声明自己的 `type`。确认信任提示之后，在命令面板中执行 **MCP: List Servers**，会看到 `bookshop` 正在运行。

!!! note
    需要 VS Code 1.99 或更高版本，安装 **GitHub Copilot** 扩展并登录（Copilot Free 就够），而且 Copilot Chat 必须处于 **Agent** 模式，因为别的模式都不会调用工具。

## 服务器没有出现 {#it-doesnt-show-up}

在改动任何宿主配置之前，先自己运行一遍启动命令：

```bash
uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py
```

什么都不打印，也不返回。这种沉默是正确的：stdio 服务器正在等宿主先在 stdin 上开口（按 `Ctrl-C` 停止）。出现 traceback 或者立刻退出，那才是真正的 bug；现在可以直接读到它，而不用隔着宿主去猜。

一旦这条命令能停在那里等待，剩下的问题几乎总是下面三种之一：

* **相对路径。** 宿主从 **它自己的** 工作目录启动你的服务器，而不是你注册时所在的目录。在需要 `/absolute/path/to/server.py` 的地方写成了 `server.py`，是所有失败里最常见的一个。如果宿主连 `uv` 也找不到，那个路径同样必须是绝对路径。
* **宿主还在跑旧配置。** 宿主在启动时读取配置。尤其是 Claude Desktop，必须 **完全退出**（不只是关掉窗口）再重新打开，对 `claude_desktop_config.json` 的修改才会生效。
* **有东西在重定向窗口期之外写到了 stdout。** 在 stdio 上，stdout **就是** 协议。SDK 在提供服务期间会把已刷新的杂散输出重定向到 stderr，但在那之前就刷新到 stdout 的输出（包装脚本的回显、无缓冲进程里导入期间的 `print()`），或者直到解释器退出才排空的带缓冲 `print()`，都会递给宿主一条损坏的消息，宿主随即断开连接。用默认的 `logging` 配置记日志，它的 stderr handler 每条记录都会刷新；自定义 handler 同样必须避开 stdout。详见 **[日志](../handlers/logging.md)**。

Claude Desktop 为每个服务器各留一份日志：`mcp-server-<NAME>.log` 是你服务器的 stderr，和记录连接情况的 `mcp.log` 放在一起，macOS 上在 `~/Library/Logs/Claude` 下，Windows 上在 `%APPDATA%\Claude\logs` 下。

这三种之外的任何问题，去看 **[故障排查](../troubleshooting.md)**。

## 回顾 {#recap}

* **宿主**（Claude Desktop、IDE）运行一个 MCP 客户端，由它通过 stdio 把你的服务器作为子进程启动。连接就是给它一条启动命令。
* 这条命令是 `uv run --with "mcp[cli]" mcp run /absolute/path/to/server.py`：无需激活 venv，在任何目录下都能用。
* **Claude Desktop** 是唯一一个 `mcp install` 能替你配置的宿主。它把同一条命令（外加 `uv` 的绝对路径、`--frozen`，以及对已安装版本的精确锁定）写进 `claude_desktop_config.json`，你永远不必自己动手。
* **Claude Code** 用 `claude mcp add bookshop -- <launch command>`。**Cursor** 用 `.cursor/mcp.json`，放在 `mcpServers` 下。**VS Code** 用 `.vscode/mcp.json`，放在 `servers` 下，每个条目带一个 `type`。
* 处处使用绝对路径，改完配置后重启宿主，并且绝不让 SDK 以外的任何东西写入 stdout。

本页每个宿主都用同一条命令连接到了同一个文件。至于这个文件能 **暴露** 什么，就是这套文档余下的内容：**[工具](../servers/tools.md)**、**[资源](../servers/resources.md)**，以及 **[运行服务器](../run/index.md)** 中 stdio 之外的每一种传输方式。
