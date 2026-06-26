"""Walk every page of resources/list by hand until next_cursor is absent."""

from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        names: list[str] = []
        cursor: str | None = None
        pages_fetched = 0
        while True:
            page = await client.list_resources(cursor=cursor)
            pages_fetched += 1
            assert pages_fetched <= 6, "server kept returning next_cursor — runaway guard"
            names.extend(r.name for r in page.resources)
            if page.next_cursor is None:  # terminate on absent, NOT on falsy: "" is a valid cursor
                break
            cursor = page.next_cursor

        assert names == ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"], names
        # server_lowlevel.py emits 3 pages of 2; server.py (MCPServer's flat registry) emits 1.
        assert pages_fetched in (1, 3), pages_fetched


if __name__ == "__main__":
    run_client(main)
