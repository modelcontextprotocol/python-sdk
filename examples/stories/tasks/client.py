"""Request task-augmented execution, then drive the task lifecycle via `tasks/*`."""

from typing import cast

import mcp_types as types

from mcp.client import Client
from mcp.server.tasks import EXTENSION_ID, RELATED_TASK_META_KEY
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        # The extensions capability map rides `server/discover` (modern only); a legacy
        # connection (today's stdio) omits it, so assert it only when present.
        if client.server_capabilities.extensions is not None:
            assert client.server_capabilities.extensions == {EXTENSION_ID: {"list": {}, "cancel": {}}}

        # `Client` exposes only spec verbs, so task-augmented calls and the
        # `tasks/*` methods drop to `client.session` (see custom_methods/). The
        # casts satisfy the closed `ClientRequest` union; at runtime the body
        # only calls `.model_dump()`.
        session = client.session
        call = types.CallToolRequest(
            params=types.CallToolRequestParams(
                name="echo", arguments={"text": "async"}, task=types.TaskMetadata(ttl=60)
            )
        )
        result = await session.send_request(cast("types.ClientRequest", call), types.CallToolResult)
        assert result.meta is not None, result
        task_id = result.meta[RELATED_TASK_META_KEY]["taskId"]
        assert isinstance(result.content[0], types.TextContent)
        assert result.content[0].text == "async", result

        get = types.GetTaskRequest(params=types.GetTaskRequestParams(task_id=task_id))
        status = await session.send_request(cast("types.ClientRequest", get), types.GetTaskResult)
        assert status.status == "completed", status

        payload_req = types.GetTaskPayloadRequest(params=types.GetTaskPayloadRequestParams(task_id=task_id))
        payload = await session.send_request(cast("types.ClientRequest", payload_req), types.CallToolResult)
        assert isinstance(payload.content[0], types.TextContent)
        assert payload.content[0].text == "async", payload


if __name__ == "__main__":
    run_client(main)
