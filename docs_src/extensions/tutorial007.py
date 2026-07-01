from collections.abc import Sequence
from typing import Any, Literal

import mcp_types as types

from mcp import Client
from mcp.client import advertise
from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding
from mcp.server.mcpserver import MCPServer

EXTENSION_ID = "com.example/jobs"


class JobParams(types.RequestParams):
    job_id: str


class JobStatus(types.Result):
    status: str


class JobStatusRequest(types.Request[JobParams, Literal["com.example/jobs.status"]]):
    method: Literal["com.example/jobs.status"] = "com.example/jobs.status"
    params: JobParams
    name_param = "jobId"  # params["jobId"] rides the Mcp-Name header


async def job_status(ctx: ServerRequestContext[Any, Any], params: JobParams) -> JobStatus:
    return JobStatus(status=f"{params.job_id} is running")


class Jobs(Extension):
    """An extension whose verb names its subject, so the header can route on it."""

    identifier = EXTENSION_ID

    def methods(self) -> Sequence[MethodBinding]:
        return [MethodBinding("com.example/jobs.status", JobParams, job_status)]


mcp = MCPServer("worker", extensions=[Jobs()])


async def main() -> None:
    async with Client(mcp, extensions=[advertise(EXTENSION_ID)]) as client:
        request = JobStatusRequest(params=JobParams(job_id="job-7"))
        result = await client.session.send_request(request, JobStatus)
        print(result.status)
        # job-7 is running
