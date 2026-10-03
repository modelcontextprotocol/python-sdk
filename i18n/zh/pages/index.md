---
translation:
  sections: [154c4309937b9f85, 3ad8fc6caa76a9b0, a07f3f5b151ab746, bf6e476b712930c0, cf0b1f13978c6623]
  tool: 1
---
# MCP Python SDK {#mcp-python-sdk}

!!! info "本文档对应 v2，即当前的稳定版本系列"
    刚接触 v2，或者从 v1 过来？**[v2 新特性](whats-new.md)** 用五分钟带你了解有哪些变化，**[迁移指南](migration.md)** 则涵盖每一项破坏性变更。还在用 v1.x？它的文档在 [v1.x 文档](https://py.sdk.modelcontextprotocol.io/v1/)。哪里不顺手或看不明白？[告诉我们](https://github.com/modelcontextprotocol/python-sdk/issues/new?template=v2-feedback.yaml)。

**Model Context Protocol (MCP)** 让应用程序以标准化的方式为 LLM 提供上下文，把 **提供** 上下文这一关注点与 LLM 交互本身分离开来。

这是 MCP 的官方 Python SDK。用它可以：

* **构建 MCP 服务器**，向任意 MCP 宿主暴露工具、资源和提示词。
* **构建 MCP 客户端**，连接到任意 MCP 服务器。
* 支持所有标准传输方式：stdio、Streamable HTTP 和 SSE。

## 环境要求 {#requirements}

需要 Python 3.10+。

## 安装 {#installation}

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

`[cli]` 附加项提供 `mcp` 命令，开发时会用到它。各个依赖的用途见 [安装](get-started/installation.md)。

## 示例 {#example}

### 创建 {#create-it}

创建文件 `server.py`：

```python title="server.py"
--8<-- "docs_src/index/tutorial001.py"
```

这就是一个完整的 MCP 服务器。

它暴露了一个 **工具** `add`，以及一个模板化的 **资源** `greeting://{name}`。

### 运行 {#run-it}

```console
uv run mcp dev server.py
```

这会启动你的服务器并打开 [MCP Inspector](https://github.com/modelcontextprotocol/inspector)，一个用来摆弄服务器的交互式界面。打开它打印出的 URL。

!!! note
    Inspector 是一个 Node.js 应用，所以 `mcp dev` 需要 `PATH` 里有 `npx`。

### 试一试 {#try-it}

在 Inspector 里进入 **Tools**，用 `a=1`、`b=2` 调用 `add`。

返回值是 `3`。✨

那个表单（一个给 `a` 的必填整数字段，另一个给 `b`）是 Inspector 根据你的类型提示生成的。Claude 也会这样做，其他所有 MCP 宿主也一样。

现在进入 **Resources**，读取 `greeting://World`：

```text
Hello, World!
```

### 回顾 {#recap}

回头再看看你 **没有** 写的东西：

* 没有 JSON Schema。`a: int, b: int` **就是** 模式。
* 没有请求解析，没有序列化，也没有校验代码。
* 完全没有协议处理。

你写了两个带类型提示和文档字符串的 Python 函数。剩下的由 SDK 完成。

## 下一步 {#where-to-go-next}

* **[快速开始](get-started/index.md)** 带你从安装一直走到一个可用、经过测试的服务器。
* 在构建一个 **使用** MCP 服务器的应用？从 **[客户端](client/index.md)** 开始。
* 已经有 FastAPI 或 Starlette 应用了？**[添加到现有应用](run/asgi.md)** 会把 MCP 服务器挂载到其中。
* 在找某条确切的错误信息？**[故障排查](troubleshooting.md)** 按报错原文逐字编排索引。
* 想知道 v2 改了什么？**[v2 新特性](whats-new.md)** 是一份五分钟导览。
* 从 v1 迁移？从 **[迁移指南](migration.md)** 开始。
* 在找某个确切的签名？**[API 参考](api/mcp/index.md)** 由源码生成。
* 借助 LLM 阅读？本文档也以 [llms.txt](https://llmstxt.org/) 格式发布：[llms.txt](https://py.sdk.modelcontextprotocol.io/llms.txt) 是各页面的索引，[llms-full.txt](https://py.sdk.modelcontextprotocol.io/llms-full.txt) 则把所有页面放在单个文件中。
