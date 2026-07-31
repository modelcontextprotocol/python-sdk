# MCP Python SDK {#mcp-python-sdk}

!!! info "本文档对应 v2，即当前的稳定发布线"
    第一次接触 v2，或者从 v1 过来？**[v2 有哪些新变化](whats-new.md)** 是一份五分钟速览，**[迁移指南](migration.md)** 则覆盖了全部破坏性变更。
    还在用 v1.x？它的文档在 [v1.x 文档](https://py.sdk.modelcontextprotocol.io/v1/)。
    有哪里不顺手或者看不明白？[告诉我们](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

**Model Context Protocol (MCP)** 让应用以标准化的方式为 LLM 提供上下文，把**提供**上下文这件事和 LLM 交互本身分离开来。

这是它的官方 Python SDK。用它可以：

* **构建 MCP 服务器**，向任意 MCP 宿主暴露工具、资源和提示词。
* **构建 MCP 客户端**，连接到任意 MCP 服务器。
* 支持所有标准传输方式：stdio、Streamable HTTP 和 SSE。

## 环境要求 {#requirements}

Python 3.10+。

## 安装 {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` 这个 extra 会带来 `mcp` 命令；开发时会用到它。
每个依赖的用途见 [安装](get-started/installation.md)。

## 示例 {#example}

### 创建 {#create-it}

创建一个文件 `server.py`：

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

这就是一个完整的 MCP 服务器。

它暴露了一个**工具** `add`，以及一个模板化的**资源** `greeting://{name}`。

### 运行 {#run-it}

```console
uv run mcp dev server.py
```

这会启动服务器，并打开 [MCP Inspector](https://github.com/modelcontextprotocol/inspector)——一个用来动手试验的交互式界面。打开它打印出来的 URL 即可。

!!! note
    Inspector 是一个 Node.js 应用，所以 `mcp dev` 需要 `PATH` 中有 `npx`。

### 试一试 {#try-it}

在 Inspector 里切到 **Tools**，用 `a=1`、`b=2` 调用 `add`。

返回值是 `3`。✨

Inspector 根据你的类型标注生成了那个表单（一个必填的整数字段 `a`，另一个是 `b`）。Claude 以及其他所有 MCP 宿主也会这么做。

现在切到 **Resources**，读取 `greeting://World`：

```text
Hello, World!
```

### 回顾 {#recap}

再看看你**没有**写的东西：

* 没有 JSON Schema。`a: int, b: int` **就是**模式。
* 没有请求解析，没有序列化，没有校验代码。
* 完全没有协议处理。

你写的是两个带类型标注和文档字符串的 Python 函数。其余的交给 SDK。

## 接下来去哪 {#where-to-go-next}

* **[快速开始](get-started/index.md)** 带你从安装走到一个可用、且测过的服务器。
* 要构建一个**使用** MCP 服务器的应用？从 **[客户端](client/index.md)** 开始。
* 已经有一个 FastAPI 或 Starlette 应用？**[接入已有应用](run/asgi.md)** 会在其中挂载一个 MCP 服务器。
* 在排查某条具体的报错信息？**[故障排查](troubleshooting.md)** 按原文逐字编排。
* 想知道 v2 有哪些变化？**[v2 有哪些新变化](whats-new.md)** 是一份五分钟速览。
* 正从 v1 迁移？从 **[迁移指南](migration.md)** 开始。
* 在找某个函数的确切签名？**[API 参考](api/mcp/index.md)** 由源码生成。
* 用 LLM 来阅读？本文档同时以 [llms.txt](https://llmstxt.org/) 格式发布：
  [llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) 是页面索引，
  [llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) 则把所有页面放在一个文件里。
