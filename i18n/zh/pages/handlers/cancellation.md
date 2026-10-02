---
translation:
  sections: [07968345fdc0b84e, 4ea8416db9efa0dc, 336a7b4c5d0a4578, 18392e805dde6717, c30d50df43f9b55c]
  tool: 1
---
# 取消 {#cancellation}

客户端可以放弃一次调用：用户按了停止，或者超时时间到了。

这时，SDK 会**取消你的处理函数**。它正在等待的 `await` 会抛出异常，函数逐层退出，它返回的任何内容都不会发送出去。大多数处理函数不需要为此做任何事。

有两类需要：有东西要清理的处理函数，以及用普通 `def` 定义的处理函数。

## 在 `async def` 工具中清理 {#clean-up-in-an-async-def-tool}

把清理代码放进 `finally`：

```python title="server.py" hl_lines="23 26-28"
--8<-- "docs_src/cancellation/tutorial001.py"
```

* 无论工具以哪种方式结束，`finally` 都会运行：正常返回、抛出异常，或者被取消。
* 需要 `await` 的清理代码要加 `shield=True`。在已取消的处理函数里，之后的每个 `await` 也都会抛出异常，所以没有这层屏蔽，`release_hold` 在第一行就会停下。
* 被屏蔽的代码块无法被取消，所以要给它设一个时间限制。这里是 `5` 秒。

!!! tip
    用 `finally`，不要用 `except`。清理完成后，取消必须继续向上传播，而 `finally` 会放行。

## 在普通 `def` 工具中提前停止 {#stop-early-in-a-plain-def-tool}

普通 `def` 工具在线程中运行，而线程无法从外部中断。工具得自己去问：

```python title="server.py" hl_lines="22 25-26"
--8<-- "docs_src/cancellation/tutorial002.py"
```

* `anyio.from_thread.check_cancelled()` 在调用仍有效时什么也不做，调用被取消后则会抛出异常。在工作单元之间调用它。
* 这里的清理代码同样放进 `finally`。线程里没有任何 await，所以不需要屏蔽。
* 从不询问的 `def` 工具会一直运行到结束，结果则被丢弃。

## 适用范围 {#where-it-applies}

提示词函数和资源函数的取消方式与工具完全相同。

在 stdio 和 Streamable HTTP 上行为一致。使用这个 SDK 的 `Client` 时，放弃调用就是取消正在等待 `call_tool` 的任务，或者让它的 `read_timeout_seconds` 耗尽。

!!! warning
    有两个 Streamable HTTP 选项会让处理函数收不到取消的消息：`2026-07-28` 连接上的 `json_response=True`，以及旧版连接上的 `stateless_http=True`。这两种情况下，无论客户端做了什么，处理函数都会运行到结束。

## 回顾 {#recap}

* 客户端放弃一次调用时，SDK 会取消处理函数：工具、提示词或资源都一样。
* `async def`：在 `finally` 中清理，需要 await 的清理代码放进 `anyio.move_on_after(seconds, shield=True)`。
* 普通 `def`：在工作单元之间调用 `anyio.from_thread.check_cancelled()`，否则工具会运行到结束。清理用普通的 `finally` 就行。
* `json_response=True`（新版连接）和 `stateless_http=True`（旧版连接）会关闭取消。

进度和取消发生在运行中的工具和它的**调用方**之间。它为**你**（运维这台服务器的人）记录的日志走的是另一条通道：**[日志](logging.md)**。
