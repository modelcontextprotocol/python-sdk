"""Asserts progress + log notifications arrive in order, then cancels a call mid-flight."""

import anyio
from mcp_types import LoggingMessageNotificationParams

from mcp.client import Client
from stories._harness import Target, run_client


async def main(target: Target, *, mode: str = "auto") -> None:
    # `logging_callback` is constructor-only on `Client`, so the list it fills
    # has to exist before the connection does.
    logs: list[LoggingMessageNotificationParams] = []

    async def on_log(params: LoggingMessageNotificationParams) -> None:
        logs.append(params)

    async with Client(target, mode=mode, logging_callback=on_log) as client:
        # ── progress + logging: a short countdown delivers exactly `steps` of each, in order ──
        updates: list[tuple[float, float | None, str | None]] = []

        async def collect(progress: float, total: float | None, message: str | None) -> None:
            updates.append((progress, total, message))

        result = await client.call_tool("countdown", {"steps": 3}, progress_callback=collect)
        assert result.structured_content == {"completed": 3, "total": 3}, result
        assert updates == [(1.0, 3.0, "step 1/3"), (2.0, 3.0, "step 2/3"), (3.0, 3.0, "step 3/3")]
        assert [(m.level, m.logger, m.data) for m in logs] == [
            ("info", "countdown", "step 1/3"),
            ("info", "countdown", "step 2/3"),
            ("info", "countdown", "step 3/3"),
        ]

        # ── cancellation: abandon the awaiting scope once the call is provably in flight ──
        in_flight = anyio.Event()
        with anyio.fail_after(5):
            with anyio.CancelScope() as scope:

                async def cancel_once_in_flight(progress: float, total: float | None, message: str | None) -> None:
                    in_flight.set()
                    scope.cancel()

                await client.call_tool("countdown", {"steps": 1_000}, progress_callback=cancel_once_in_flight)

        assert in_flight.is_set(), "the call must have started before it was cancelled"
        assert scope.cancelled_caught, "abandoning the scope should have cancelled the in-flight call"

        # The session survives cancellation: a follow-up call still works.
        after = await client.call_tool("countdown", {"steps": 1}, progress_callback=collect)
        assert after.structured_content == {"completed": 1, "total": 1}


if __name__ == "__main__":
    run_client(main)
