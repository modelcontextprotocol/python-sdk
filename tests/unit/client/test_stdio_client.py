from __future__ import annotations

import anyio
import pytest

from mcp.client import stdio as stdio_module
from mcp.client.stdio import StdioServerParameters, stdio_client


class DummyStdin:
    async def send(self, data: bytes) -> None:
        return None

    async def aclose(self) -> None:
        return None


class DummyProcess:
    def __init__(self) -> None:
        self.stdin = DummyStdin()
        self.stdout = object()

    async def __aenter__(self) -> "DummyProcess":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def wait(self) -> None:
        return None


class BrokenPipeStream:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __aiter__(self) -> "BrokenPipeStream":
        return self

    async def __anext__(self) -> str:
        raise BrokenPipeError()


@pytest.mark.anyio
async def test_stdio_client_handles_broken_pipe(monkeypatch) -> None:
    server = StdioServerParameters(command="dummy")

    async def fake_checkpoint() -> None:
        nonlocal checkpoint_calls
        checkpoint_calls += 1

    async def fake_create_process(*args, **kwargs) -> DummyProcess:
        return DummyProcess()

    checkpoint_calls = 0

    monkeypatch.setattr(stdio_module.anyio.lowlevel, "checkpoint", fake_checkpoint)
    monkeypatch.setattr(stdio_module, "TextReceiveStream", BrokenPipeStream)
    monkeypatch.setattr(stdio_module, "_create_platform_compatible_process", fake_create_process)

    async with stdio_client(server):
        # Allow background tasks to run once so the broken pipe is triggered.
        await anyio.sleep(0)

    assert checkpoint_calls >= 1
