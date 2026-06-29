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

        # The log also holds era-dependent bookkeeping (legacy: initialize + notifications/initialized;
        # modern HTTP: server/discover). Keep only the tools/* methods this client drove.
        seen = [m for m in result.structured_content["result"] if m.startswith("tools/")]
        # No :done after tools/call — the handler ran inside the middleware frame. Assert
        # only the tail: a long-lived server's log accumulates across clients.
        assert seen[-3:] == ["tools/list", "tools/list:done", "tools/call"], seen


if __name__ == "__main__":
    run_client(main)
