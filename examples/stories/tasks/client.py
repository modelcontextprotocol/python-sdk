"""Start a tool call as a task, then poll the task to completion and fetch its result.

`Client` exposes only spec verbs, so the `task` augmentation and the `tasks/*`
methods drop to `client.session`. The thin `_start_task` / `_get_task` /
`_task_result` helpers keep that `cast` noise out of the story below; `main`
itself reads as: kick off the work, see it as a task, collect the report.
"""

from typing import cast

import mcp_types as types

from mcp.client import Client, ClientSession
from mcp.server.tasks import EXTENSION_ID, RELATED_TASK_META_KEY
from stories._harness import Target, run_client


async def _start_task(session: ClientSession, name: str, arguments: dict[str, object]) -> types.CallToolResult:
    """Call a tool with task augmentation; the result carries the task id in `_meta`."""
    request = types.CallToolRequest(
        params=types.CallToolRequestParams(name=name, arguments=arguments, task=types.TaskMetadata(ttl=60))
    )
    return await session.send_request(cast("types.ClientRequest", request), types.CallToolResult)


async def _get_task(session: ClientSession, task_id: str) -> types.GetTaskResult:
    request = types.GetTaskRequest(params=types.GetTaskRequestParams(task_id=task_id))
    return await session.send_request(cast("types.ClientRequest", request), types.GetTaskResult)


async def _task_result(session: ClientSession, task_id: str) -> types.CallToolResult:
    request = types.GetTaskPayloadRequest(params=types.GetTaskPayloadRequestParams(task_id=task_id))
    return await session.send_request(cast("types.ClientRequest", request), types.CallToolResult)


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        # The extensions capability map rides `server/discover` (modern only); a legacy
        # connection (today's stdio) omits it, so assert it only when present.
        if client.server_capabilities.extensions is not None:
            assert client.server_capabilities.extensions == {EXTENSION_ID: {"list": {}, "cancel": {}}}

        started = await _start_task(client.session, "render_report", {"title": "Q3", "sections": 2})
        task_id = started.meta[RELATED_TASK_META_KEY]["taskId"] if started.meta else None
        assert task_id is not None, started

        task = await _get_task(client.session, task_id)
        assert task.status == "completed", task

        report = await _task_result(client.session, task_id)
        assert isinstance(report.content[0], types.TextContent)
        assert report.content[0].text.startswith("# Q3"), report


if __name__ == "__main__":
    run_client(main)
