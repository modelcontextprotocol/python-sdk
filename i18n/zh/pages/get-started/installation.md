---
translation:
  sections: [6e2f9bab94d5ed36, 8cf653388f69e28b, 6fd9ea2f65de0df6]
  tool: 1
---
# 安装 {#installation}

Python SDK 在 PyPI 上的包名是 [`mcp`](https://pypi.org/project/mcp/)，需要 **Python 3.10+**。

本文档描述的是 **v2**，也就是当前的稳定版本系列：

=== "uv"

    ```bash
    uv add "mcp[cli]"
    ```

=== "pip"

    ```bash
    pip install "mcp[cli]"
    ```

!!! note "从 v1 迁移过来？"
    v2 是包含破坏性变更的主版本，**[迁移指南](../migration.md)** 涵盖了其中每一处。如果你的**包**依赖 `mcp` 且还没准备好迁移，请保留 `<2` 的版本上限（例如 `mcp>=1.28,<2`），这样在未锁定版本的情况下，依赖解析仍会停留在 1.x 系列。

## 安装了什么 {#what-gets-installed}

使用 SDK 并不需要了解这些，不过如果你好奇每个依赖是做什么的：

* `mcp-types`：所有协议类型（请求、结果、内容块）独立成一个包，版本与 SDK 同步发布。依赖 `mcp` 的代码通过 `mcp.types` 这个别名导入它（本文档里每一处 `from mcp.types import ...` 都是这样）；只有在安装了 `mcp-types` 却没有安装 SDK 的项目里，才直接导入 `mcp_types`。
* [`anyio`](https://anyio.readthedocs.io/)：异步运行时。整个 SDK 都基于 anyio 编写，因此既能跑在 `asyncio` 上，也能跑在 `trio` 上。
* [`pydantic`](https://docs.pydantic.dev/)：每个 `mcp.types` 模型都构建在它之上，所有的模式生成和校验也由它完成。
* [`httpx2`](https://pypi.org/project/httpx2/)：支撑 Streamable HTTP 和 SSE **客户端**传输方式的 HTTP 客户端，内置对 server-sent events 的支持。
* [`starlette`](https://www.starlette.io/)、[`uvicorn`](https://www.uvicorn.org/)、[`sse-starlette`](https://pypi.org/project/sse-starlette/) 和 [`python-multipart`](https://pypi.org/project/python-multipart/)：HTTP **服务器端**传输方式。
* [`jsonschema`](https://pypi.org/project/jsonschema/)：对照工具声明的输出模式，校验工具的结构化输出。
* [`pyjwt[crypto]`](https://pyjwt.readthedocs.io/)：授权所需的 OAuth 令牌处理。
* [`opentelemetry-api`](https://opentelemetry-python.readthedocs.io/)：仅包含轻量级的 API，所以除非你自己安装 OpenTelemetry SDK 和导出器，否则 SDK 的追踪中间件不会带来任何开销。
* [`typing-extensions`](https://typing-extensions.readthedocs.io/) 和 [`typing-inspection`](https://pypi.org/project/typing-inspection/)：在 Python 3.10 上提供现代的类型标注特性。
* [`pywin32`](https://pypi.org/project/pywin32/)：仅 Windows 需要，用于 `stdio` 子进程管理。

## 可选附加依赖 {#optional-extras}

* `mcp[cli]` 会额外安装 [`typer`](https://typer.tiangolo.com/) 和 [`python-dotenv`](https://pypi.org/project/python-dotenv/)，供 `mcp` 命令行工具（`mcp dev`、`mcp run`、`mcp install`）使用。开发期间会用到它；部署后的服务器里未必需要。
* `mcp[rich]` 会额外安装 [`rich`](https://rich.readthedocs.io/)，让服务器日志更美观。
