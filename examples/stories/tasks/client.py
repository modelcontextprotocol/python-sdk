"""Declare the tasks extension and let `Client.call_tool` drive the task transparently.

The client declares `io.modelcontextprotocol/tasks` (by constructing
`TasksExtension()` into `Client(extensions=...)`),
so the server is free to answer `tools/call` with a `CreateTaskResult`. SEP-2663
advises clients to keep a fixed public contract and drive the polling internally —
`Client.call_tool` does exactly that, so the modern path is the same typed call a
task-less server would get. A compact manual leg then shows the raw wire flow:
`session.call_tool(allow_claimed=True)` for the typed `CreateTaskResult`, and the
typed `mcp.client.tasks` functions (`get_task`, `wait_task`) to drive `tasks/get`.
"""

import mcp_types as types

from mcp.client import Client, TasksExtension
from mcp.client.tasks import get_task, wait_task
from mcp.shared.tasks import EXTENSION_ID, CreateTaskResult
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode, extensions=[TasksExtension()]) as client:
        # The transparent path. On the modern wire the server augments this
        # tools/call into a task (we declared the extension) and Client.call_tool
        # polls tasks/get to the final result; on a legacy connection the
        # extension cannot be negotiated, the server must not augment, and the
        # very same call simply returns the plain CallToolResult.
        result = await client.call_tool("render_report", {"title": "Q3", "sections": 2})
        assert isinstance(result.content[0], types.TextContent), result
        assert result.content[0].text.startswith("# Q3"), result
        # No 2025-style related-task _meta either; the task plumbing never leaks
        # into the surfaced result.
        assert result.meta is None, result

        if client.server_capabilities.extensions is None:
            # Legacy wire: nothing more to show — the degradation above is the point.
            return
        assert client.server_capabilities.extensions == {EXTENSION_ID: {}}

        # The manual leg: the same flow driven by hand. allow_claimed=True hands
        # back the typed CreateTaskResult instead of polling, and get_task fetches
        # one tasks/get snapshot with the outcome inlined.
        created = await client.session.call_tool("render_report", {"title": "Q3", "sections": 1}, allow_claimed=True)
        assert isinstance(created, CreateTaskResult), created

        task = await get_task(client.session, created.task_id)
        assert task.status == "completed", task
        assert task.result is not None, task
        assert task.result["content"][0]["text"].startswith("# Q3"), task

        # wait_task polls the same task to its final CallToolResult — from the
        # bare persisted id here, the resume-after-reconnect shape.
        final = await wait_task(client.session, created.task_id)
        assert isinstance(final.content[0], types.TextContent), final
        assert final.content[0].text.startswith("# Q3"), final


if __name__ == "__main__":
    run_client(main)
