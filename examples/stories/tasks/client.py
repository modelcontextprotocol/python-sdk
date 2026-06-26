"""Declare the tasks extension, let the server defer a tool call, then poll tasks/get.

The client declares `io.modelcontextprotocol/tasks` (via `Client(extensions=...)`),
so the server is free to answer `tools/call` with a `CreateTaskResult`. `Client`
exposes only spec verbs, so the augmented call and `tasks/get` drop to
`client.session`; the thin `_send` helper keeps that out of the story below.
"""

from typing import Any, Literal, cast

import mcp_types as types
from pydantic import TypeAdapter

from mcp.client import Client, ClientSession, advertise
from mcp.server.tasks import EXTENSION_ID, GetTaskRequestParams
from stories._harness import Target, run_client

_RAW: TypeAdapter[dict[str, Any]] = TypeAdapter(dict)


class _GetTaskRequest(types.Request[GetTaskRequestParams, Literal["tasks/get"]]):
    method: Literal["tasks/get"] = "tasks/get"
    params: GetTaskRequestParams


async def _send(session: ClientSession, request: types.Request[Any, Any]) -> dict[str, Any]:
    """Send a request whose result has a non-spec (extension) shape; return the raw dict."""
    return await session.send_request(cast("types.ClientRequest", request), cast("Any", _RAW))


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode, extensions=[advertise(EXTENSION_ID)]) as client:
        # The extension is a modern-only capability negotiated over server/discover.
        # A legacy connection cannot carry it, and the server then must not
        # augment, so the task flow only runs once it is negotiated.
        if client.server_capabilities.extensions is None:
            return
        assert client.server_capabilities.extensions == {EXTENSION_ID: {}}

        # The server augments this tools/call into a task because we declared the extension.
        call = types.CallToolRequest(
            params=types.CallToolRequestParams(name="render_report", arguments={"title": "Q3", "sections": 2})
        )
        created = await _send(client.session, call)
        assert created["resultType"] == "task", created
        task_id = created["taskId"]

        task = await _send(client.session, _GetTaskRequest(params=GetTaskRequestParams(task_id=task_id)))
        assert task["status"] == "completed", task
        assert task["result"]["content"][0]["text"].startswith("# Q3"), task


if __name__ == "__main__":
    run_client(main)
