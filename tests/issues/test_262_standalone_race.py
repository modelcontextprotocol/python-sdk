"""
Standalone reproduction of the exact pattern that could cause issue #262.

This file recreates the EXACT architecture of stdio_client + ClientSession
WITHOUT using any MCP SDK code, to isolate and reproduce the race condition.

Architecture being simulated:
1. stdio_client creates 0-capacity memory streams
2. stdio_client starts stdout_reader and stdin_writer with start_soon (not awaited)
3. stdio_client yields streams to caller
4. ClientSession.__aenter__ starts _receive_loop with start_soon (not awaited)
5. ClientSession returns to caller
6. Caller calls send_request which sends to write_stream
7. If tasks haven't started, send blocks forever on 0-capacity stream

This is the EXACT pattern from:
- src/mcp/client/stdio/__init__.py lines 117-118, 186-187, 189
- src/mcp/shared/session.py line 224
"""

import json
import subprocess
import sys
import textwrap
from contextlib import asynccontextmanager

import anyio
import pytest
from anyio.streams.text import TextReceiveStream

# Minimal server script
SERVER_SCRIPT = textwrap.dedent('''
    import json
    import sys
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        req = json.loads(line)
        rid = req.get("id")
        method = req.get("method", "")
        if method == "test":
            print(json.dumps({"id": rid, "result": "ok"}), flush=True)
        elif method == "slow":
            import time
            time.sleep(0.1)
            print(json.dumps({"id": rid, "result": "slow_ok"}), flush=True)
''').strip()


# =============================================================================
# Simulation of stdio_client
# =============================================================================


@asynccontextmanager
async def simulated_stdio_client(cmd: list[str], delay_before_yield: float = 0):
    """
    Simulates stdio_client exactly:
    1. Create 0-capacity streams
    2. Start reader/writer with start_soon
    3. Yield to caller
    """
    # EXACTLY like stdio_client lines 117-118
    read_stream_writer, read_stream = anyio.create_memory_object_stream[dict](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[dict](0)

    process = await anyio.open_process(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
    )

    async def stdout_reader():
        """EXACTLY like stdio_client stdout_reader."""
        assert process.stdout
        try:
            async with read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(process.stdout, encoding="utf-8"):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        if line.strip():
                            msg = json.loads(line)
                            await read_stream_writer.send(msg)
        except anyio.ClosedResourceError:
            pass

    async def stdin_writer():
        """EXACTLY like stdio_client stdin_writer."""
        assert process.stdin
        try:
            async with write_stream_reader:
                async for msg in write_stream_reader:
                    json_str = json.dumps(msg) + "\n"
                    await process.stdin.send(json_str.encode())
        except anyio.ClosedResourceError:
            pass

    async with anyio.create_task_group() as tg:
        async with process:
            # EXACTLY like stdio_client lines 186-187: start_soon, NOT awaited!
            tg.start_soon(stdout_reader)
            tg.start_soon(stdin_writer)

            # Optional delay to test race timing
            if delay_before_yield > 0:
                await anyio.sleep(delay_before_yield)

            # EXACTLY like stdio_client line 189
            try:
                yield read_stream, write_stream
            finally:
                if process.stdin:
                    try:
                        await process.stdin.aclose()
                    except Exception:
                        pass
                try:
                    with anyio.fail_after(1):
                        await process.wait()
                except TimeoutError:
                    process.terminate()


# =============================================================================
# Simulation of ClientSession
# =============================================================================


class SimulatedClientSession:
    """
    Simulates ClientSession exactly:
    1. __aenter__ starts _receive_loop with start_soon
    2. send_request sends to write_stream (0-capacity)
    3. Waits for response from read_stream
    """

    def __init__(self, read_stream, write_stream, delay_in_receive_loop: float = 0):
        self._read_stream = read_stream
        self._write_stream = write_stream
        self._delay_in_receive_loop = delay_in_receive_loop
        self._request_id = 0
        self._response_streams = {}
        self._task_group = None

    async def __aenter__(self):
        # EXACTLY like BaseSession.__aenter__
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        # start_soon, NOT awaited!
        self._task_group.start_soon(self._receive_loop)
        return self

    async def __aexit__(self, *args):
        self._task_group.cancel_scope.cancel()
        return await self._task_group.__aexit__(*args)

    async def _receive_loop(self):
        """EXACTLY like BaseSession._receive_loop pattern."""
        # This is where we can inject delay to widen the race window
        if self._delay_in_receive_loop > 0:
            await anyio.sleep(self._delay_in_receive_loop)

        try:
            async for msg in self._read_stream:
                request_id = msg.get("id")
                if request_id in self._response_streams:
                    await self._response_streams[request_id].send(msg)
        except anyio.ClosedResourceError:
            pass

    async def send_request(self, method: str, timeout: float = 5.0) -> dict:
        """EXACTLY like BaseSession.send_request pattern."""
        request_id = self._request_id
        self._request_id += 1

        # Create response stream with capacity 1 (like the real code)
        response_sender, response_receiver = anyio.create_memory_object_stream[dict](1)
        self._response_streams[request_id] = response_sender

        try:
            request = {"id": request_id, "method": method}

            # This is THE CRITICAL SEND on 0-capacity stream!
            # If stdin_writer hasn't started, this blocks forever
            await self._write_stream.send(request)

            # Wait for response
            with anyio.fail_after(timeout):
                response = await response_receiver.receive()
                return response
        finally:
            del self._response_streams[request_id]


# =============================================================================
# TESTS
# =============================================================================


@pytest.mark.anyio
async def test_simulated_basic():
    """Basic test of simulated architecture - should work."""
    cmd = [sys.executable, "-u", "-c", SERVER_SCRIPT]

    with anyio.fail_after(10):
        async with simulated_stdio_client(cmd) as (read, write):
            async with SimulatedClientSession(read, write) as session:
                result = await session.send_request("test")
                assert result["result"] == "ok"


@pytest.mark.anyio
async def test_simulated_with_receive_loop_delay():
    """
    Add delay in receive_loop to widen the race window.

    The receive_loop is started with start_soon. If we add a delay at its start,
    it creates a window where send_request might try to send before the chain
    of tasks is ready to process.
    """
    cmd = [sys.executable, "-u", "-c", SERVER_SCRIPT]

    success_count = 0
    iterations = 30

    for i in range(iterations):
        try:
            with anyio.fail_after(2):
                async with simulated_stdio_client(cmd) as (read, write):
                    # Add delay in receive_loop
                    async with SimulatedClientSession(
                        read, write, delay_in_receive_loop=0.01
                    ) as session:
                        result = await session.send_request("test", timeout=1)
                        assert result["result"] == "ok"
                        success_count += 1
        except TimeoutError:
            print(f"\nHang detected at iteration {i}!")
            pytest.fail(f"REPRODUCED! Hang at iteration {i}")

    print(f"\n{success_count}/{iterations} iterations completed")


@pytest.mark.anyio
async def test_simulated_multiple_requests():
    """Test multiple sequential requests."""
    cmd = [sys.executable, "-u", "-c", SERVER_SCRIPT]

    with anyio.fail_after(10):
        async with simulated_stdio_client(cmd) as (read, write):
            async with SimulatedClientSession(read, write) as session:
                for i in range(10):
                    result = await session.send_request("test")
                    assert result["result"] == "ok"


@pytest.mark.anyio
async def test_race_window_pure_streams():
    """
    Test JUST the 0-capacity stream + start_soon pattern in isolation.

    This removes all the subprocess complexity to focus on the core race.
    """
    deadlock_detected = False

    for iteration in range(100):
        # Create 0-capacity streams like stdio_client
        write_stream_sender, write_stream_receiver = anyio.create_memory_object_stream[dict](0)

        async def consumer():
            # Add delay to simulate the task not being ready immediately
            await anyio.sleep(0.001)
            async with write_stream_receiver:
                async for msg in write_stream_receiver:
                    return msg

        try:
            async with anyio.create_task_group() as tg:
                # Start consumer with start_soon (not awaited!)
                tg.start_soon(consumer)

                # Immediately try to send
                async with write_stream_sender:
                    with anyio.fail_after(0.01):  # Very short timeout
                        await write_stream_sender.send({"test": iteration})

        except TimeoutError:
            deadlock_detected = True
            print(f"\nDeadlock detected at iteration {iteration}!")
            break
        except anyio.get_cancelled_exc_class():
            pass

    if deadlock_detected:
        pytest.fail("REPRODUCED! Pure stream race condition caused deadlock!")


@pytest.mark.anyio
async def test_aggressive_race_condition():
    """
    Most aggressive test: multiple sources of delay to maximize race chance.
    """
    cmd = [sys.executable, "-u", "-c", SERVER_SCRIPT]

    for iteration in range(50):
        try:
            with anyio.fail_after(3):
                # Add delay before yield in stdio_client simulation
                async with simulated_stdio_client(cmd, delay_before_yield=0) as (read, write):
                    # Add delay in receive_loop
                    async with SimulatedClientSession(
                        read, write, delay_in_receive_loop=0.005
                    ) as session:
                        # Multiple requests in quick succession
                        for _ in range(3):
                            result = await session.send_request("test", timeout=1)
                            assert result["result"] == "ok"

        except TimeoutError:
            pytest.fail(f"REPRODUCED! Aggressive test deadlocked at iteration {iteration}!")


# =============================================================================
# Manual verification tests
# =============================================================================


@pytest.mark.anyio
async def test_verify_zero_capacity_blocks():
    """
    Verify that 0-capacity streams DO block when no receiver is ready.

    This is a sanity check that our understanding is correct.
    """
    sender, receiver = anyio.create_memory_object_stream[str](0)

    blocked = False

    async def try_send():
        nonlocal blocked
        try:
            with anyio.fail_after(0.1):
                await sender.send("test")
        except TimeoutError:
            blocked = True

    async with sender, receiver:
        # Don't start a receiver, just try to send
        await try_send()

    assert blocked, "Send should have blocked on 0-capacity stream with no receiver!"
    print("\nConfirmed: 0-capacity stream blocks when no receiver is ready")


@pytest.mark.anyio
async def test_verify_start_soon_doesnt_wait():
    """
    Verify that start_soon doesn't wait for the task to actually start running.

    This is key to the race condition.
    """
    started = False

    async def task():
        nonlocal started
        started = True

    async with anyio.create_task_group() as tg:
        tg.start_soon(task)

        # Check IMMEDIATELY after start_soon
        immediate_started = started

        # Now wait a bit
        await anyio.sleep(0.01)
        delayed_started = started

    print(f"\nImmediate: started={immediate_started}, After delay: started={delayed_started}")

    # The task might or might not have started immediately
    # The point is that start_soon doesn't GUARANTEE it started
    assert delayed_started, "Task should have started after delay"


@pytest.mark.anyio
async def test_confirm_race_exists():
    """
    Try to definitively prove the race exists by measuring timing.
    """
    import time

    sender, receiver = anyio.create_memory_object_stream[str](0)

    receiver_start_time = None
    send_complete_time = None

    async def delayed_receiver():
        nonlocal receiver_start_time
        await anyio.sleep(0.01)  # 10ms delay
        receiver_start_time = time.perf_counter()
        async with receiver:
            async for item in receiver:
                return item

    async def sender_task():
        nonlocal send_complete_time
        async with sender:
            await sender.send("test")
            send_complete_time = time.perf_counter()

    async with anyio.create_task_group() as tg:
        tg.start_soon(delayed_receiver)
        tg.start_soon(sender_task)

    # The send should have completed only AFTER receiver started
    print(f"\nReceiver started at: {receiver_start_time}")
    print(f"Send completed at: {send_complete_time}")

    if send_complete_time > receiver_start_time:
        print("Send blocked until receiver was ready - as expected for 0-capacity stream")
    else:
        print("Send completed before receiver started?! This shouldn't happen.")
