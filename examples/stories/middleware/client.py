"""Prove the middleware wrapped both `tools/list` and the in-flight `tools/call`."""

from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        listed = await client.list_tools()
        assert [t.name for t in listed.tools] == ["audit_log"]

        result = await client.call_tool("audit_log", {})
        assert not result.is_error
        assert result.structured_content is not None, result

        # Era-neutral: legacy adds initialize + notifications/initialized; modern HTTP
        # adds server/discover; modern in-memory adds nothing. Filter to the methods
        # this client drove.
        seen = [m for m in result.structured_content["result"] if m.startswith("tools/")]
        # tools/call:done is absent — the handler ran inside the middleware frame.
        assert seen == ["tools/list", "tools/list:done", "tools/call"], seen


if __name__ == "__main__":
    run_client(main)
