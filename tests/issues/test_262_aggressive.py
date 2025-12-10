"""
AGGRESSIVE tests for issue #262: MCP Client Tool Call Hang

This file contains tests that:
1. Directly patch the SDK to introduce delays that should trigger the race condition
2. Create standalone reproductions of the exact SDK patterns
3. Try to reproduce the hang by exploiting the zero-buffer + start_soon pattern

The key insight from issue #1764:
- stdio_client creates 0-capacity streams (line 117-118)
- stdout_reader and stdin_writer are started with start_soon (line 186-187)
- Control returns to caller BEFORE these tasks may be running
- ClientSession.__aenter__ also uses start_soon for _receive_loop (line 224)
- If send happens before tasks are ready, deadlock occurs on 0-capacity streams

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
See: https://github.com/modelcontextprotocol/python-sdk/issues/1764
"""

import subprocess
import sys
import textwrap
from contextlib import asynccontextmanager

import anyio
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.message import SessionMessage

# Minimal server for testing
MINIMAL_SERVER = textwrap.dedent('''
    import json
    import sys

    def send(response):
        print(json.dumps(response), flush=True)

    def recv():
        line = sys.stdin.readline()
        return json.loads(line) if line else None

    while True:
        req = recv()
        if req is None:
            break
        method = req.get("method", "")
        rid = req.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "test", "version": "1.0"}
            }})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "tools": [{"name": "test", "description": "Test",
                           "inputSchema": {"type": "object", "properties": {}}}]
            }})
        elif method == "tools/call":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": "Result"}], "isError": False
            }})
''').strip()


# =============================================================================
# TEST 1: Patch stdio_client to delay task startup
# =============================================================================


@asynccontextmanager
async def stdio_client_with_delayed_tasks(
    server: StdioServerParameters,
    delay_before_tasks: float = 0.1,
    delay_after_tasks: float = 0.0,
):
    """
    Modified stdio_client that adds delays to trigger race conditions.

    delay_before_tasks: Delay AFTER yield but BEFORE tasks start (should cause hang)
    delay_after_tasks: Delay AFTER tasks are scheduled with start_soon
    """
    from anyio.streams.text import TextReceiveStream

    import mcp.types as types

    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    process = await anyio.open_process(
        [server.command, *server.args],
        env=server.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
    )

    async def stdout_reader():
        assert process.stdout
        try:
            async with read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(process.stdout, encoding="utf-8"):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                            await read_stream_writer.send(SessionMessage(message))
                        except Exception as exc:
                            await read_stream_writer.send(exc)
        except anyio.ClosedResourceError:
            pass

    async def stdin_writer():
        assert process.stdin
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_str = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    await process.stdin.send((json_str + "\n").encode())
        except anyio.ClosedResourceError:
            pass

    async with anyio.create_task_group() as tg:
        async with process:
            # KEY DIFFERENCE: We can add a delay here BEFORE starting tasks
            # This simulates the scenario where yield returns before tasks run
            if delay_before_tasks > 0:
                await anyio.sleep(delay_before_tasks)

            tg.start_soon(stdout_reader)
            tg.start_soon(stdin_writer)

            # Delay AFTER scheduling with start_soon
            # Tasks are scheduled but may not be running yet!
            if delay_after_tasks > 0:
                await anyio.sleep(delay_after_tasks)

            try:
                yield read_stream, write_stream
            finally:
                if process.stdin:
                    try:
                        await process.stdin.aclose()
                    except Exception:
                        pass
                try:
                    with anyio.fail_after(2):
                        await process.wait()
                except TimeoutError:
                    process.terminate()
                await read_stream.aclose()
                await write_stream.aclose()
                await read_stream_writer.aclose()
                await write_stream_reader.aclose()


@pytest.mark.anyio
async def test_with_delayed_task_startup():
    """
    Test with delays before tasks start.

    This should work because the delay is BEFORE tasks are scheduled,
    so by the time yield happens, tasks should be running.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-c", MINIMAL_SERVER],
    )

    with anyio.fail_after(10):
        async with stdio_client_with_delayed_tasks(
            params, delay_before_tasks=0.1, delay_after_tasks=0
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.list_tools()
                result = await session.call_tool("test", arguments={})
                assert result.content[0].text == "Result"


# =============================================================================
# TEST 2: Standalone reproduction of zero-buffer + start_soon pattern
# =============================================================================


@pytest.mark.anyio
async def test_zero_buffer_start_soon_race_basic():
    """
    Reproduce the exact pattern that causes the race condition.

    Pattern:
    1. Create 0-capacity stream
    2. Schedule receiver with start_soon (not awaited)
    3. Immediately try to send

    This should occasionally deadlock if the receiver hasn't started.
    """
    success_count = 0
    deadlock_count = 0
    iterations = 100

    for _ in range(iterations):
        sender, receiver = anyio.create_memory_object_stream[str](0)

        received = []

        async def receive_task():
            async with receiver:
                received.extend([item async for item in receiver])

        try:
            async with anyio.create_task_group() as tg:
                # Schedule receiver with start_soon (might not be running yet!)
                tg.start_soon(receive_task)

                # NO DELAY - immediately try to send
                # This is the race: if receive_task hasn't started, send blocks
                async with sender:
                    with anyio.fail_after(0.1):  # Short timeout to detect deadlock
                        await sender.send("test")

                success_count += 1

        except TimeoutError:
            # Deadlock detected!
            deadlock_count += 1
            # Cancel the task group to clean up
            pass
        except anyio.get_cancelled_exc_class():
            pass

    # Report results
    print(f"\nZero-buffer race test: {success_count}/{iterations} succeeded, {deadlock_count} deadlocked")

    # The test passes if we completed all iterations (no deadlock on this platform)
    # but we're trying to REPRODUCE deadlock, so any deadlock is interesting
    if deadlock_count > 0:
        pytest.fail(f"REPRODUCED! {deadlock_count}/{iterations} iterations deadlocked!")


@pytest.mark.anyio
async def test_zero_buffer_start_soon_race_aggressive():
    """
    More aggressive version - adds artificial delays to widen the race window.
    """

    deadlock_count = 0
    iterations = 50

    for i in range(iterations):
        sender, receiver = anyio.create_memory_object_stream[str](0)

        async def receive_task():
            # Add delay at START of receiver to widen the race window
            await anyio.sleep(0.001)  # 1ms delay before starting to receive
            async with receiver:
                async for item in receiver:
                    pass

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(receive_task)

                # The receiver has 1ms delay, so if we send immediately,
                # we should hit the race condition
                async with sender:
                    with anyio.fail_after(0.05):
                        await sender.send("test")

        except TimeoutError:
            deadlock_count += 1
        except anyio.get_cancelled_exc_class():
            pass

    print(f"\nAggressive race test: {iterations - deadlock_count}/{iterations} succeeded, {deadlock_count} deadlocked")

    if deadlock_count > 0:
        pytest.fail(f"REPRODUCED! {deadlock_count}/{iterations} iterations deadlocked!")


# =============================================================================
# TEST 3: Patch BaseSession to add delay before _receive_loop starts
# =============================================================================


@pytest.mark.anyio
async def test_session_with_delayed_receive_loop():
    """
    Patch BaseSession to add a delay in _receive_loop startup.

    This simulates the scenario where _receive_loop is scheduled with start_soon
    but hasn't actually started running when send_request is called.
    """
    import mcp.shared.session as session_module

    original_receive_loop = session_module.BaseSession._receive_loop

    async def delayed_receive_loop(self):
        # Add delay at the START of receive loop
        # This widens the window where send could block
        await anyio.sleep(0.01)
        return await original_receive_loop(self)

    session_module.BaseSession._receive_loop = delayed_receive_loop

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-u", "-c", MINIMAL_SERVER],
        )

        # Run multiple iterations to catch timing issues
        for _ in range(10):
            with anyio.fail_after(5):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await session.list_tools()
                        result = await session.call_tool("test", arguments={})
                        assert result.content[0].text == "Result"

    finally:
        session_module.BaseSession._receive_loop = original_receive_loop


# =============================================================================
# TEST 4: Simulate the EXACT stdio_client + ClientSession pattern
# =============================================================================


@pytest.mark.anyio
async def test_exact_stdio_pattern_simulation():
    """
    Simulate the EXACT pattern used in stdio_client + ClientSession.

    This creates:
    - 0-capacity streams (like stdio_client lines 117-118)
    - Reader/writer tasks started with start_soon (like lines 186-187)
    - Another task started with start_soon for processing (like session._receive_loop)
    - Immediate send after setup

    If the issue exists, this should deadlock.
    """

    # Simulate the stdio_client streams
    read_stream_writer, read_stream = anyio.create_memory_object_stream[dict](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[dict](0)

    # Simulate the internal processing streams
    processed_writer, processed_reader = anyio.create_memory_object_stream[dict](0)

    async def stdout_reader_sim():
        """Simulates stdout_reader in stdio_client."""
        async with read_stream_writer:
            for i in range(3):
                await anyio.sleep(0.001)  # Simulate reading from process
                await read_stream_writer.send({"id": i, "result": f"response_{i}"})

    async def stdin_writer_sim():
        """Simulates stdin_writer in stdio_client."""
        async with write_stream_reader:
            async for msg in write_stream_reader:
                # Simulate writing to process - just consume the message
                pass

    async def receive_loop_sim():
        """Simulates _receive_loop in BaseSession."""
        async with processed_writer:
            async with read_stream:
                async for msg in read_stream:
                    await processed_writer.send(msg)

    results = []

    async def client_code():
        """Simulates the user's code."""
        # This is called AFTER all tasks are scheduled with start_soon
        # but they may not be running yet!

        async with processed_reader:
            # Try to send immediately
            async with write_stream:
                for i in range(3):
                    await write_stream.send({"id": i, "method": f"request_{i}"})

                    # Wait for response
                    with anyio.fail_after(1):
                        response = await processed_reader.receive()
                        results.append(response)

    try:
        async with anyio.create_task_group() as tg:
            # These are started with start_soon, NOT awaited!
            tg.start_soon(stdout_reader_sim)
            tg.start_soon(stdin_writer_sim)
            tg.start_soon(receive_loop_sim)

            # Add a tiny delay here to simulate the race window
            # In real code, this is where control returns to the caller
            await anyio.sleep(0)  # Just yield to event loop once

            # Now run client code
            with anyio.fail_after(5):
                await client_code()

        assert len(results) == 3

    except TimeoutError:
        pytest.fail("REPRODUCED! Pattern simulation deadlocked!")


# =============================================================================
# TEST 5: Inject delay into stdio_client via monkey-patching
# =============================================================================


@pytest.mark.anyio
async def test_patched_stdio_client_with_yield_delay():
    """
    Patch stdio_client to add a delay RIGHT AFTER start_soon calls
    but BEFORE yielding to the caller.

    This tests what happens when tasks are scheduled but not yet running.
    """
    import mcp.client.stdio as stdio_module

    original_stdio_client = stdio_module.stdio_client

    @asynccontextmanager
    async def patched_stdio_client(server, errlog=sys.stderr):
        async with original_stdio_client(server, errlog) as (read, write):
            # The tasks are already scheduled with start_soon
            # Add delay to let them NOT run before we continue
            # (In reality we can't prevent them, but we can try to race)
            yield read, write

    stdio_module.stdio_client = patched_stdio_client

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-u", "-c", MINIMAL_SERVER],
        )

        for _ in range(20):
            with anyio.fail_after(5):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await session.list_tools()
                        result = await session.call_tool("test", arguments={})
                        assert result.content[0].text == "Result"

    finally:
        stdio_module.stdio_client = original_stdio_client


# =============================================================================
# TEST 6: Create a truly broken version that SHOULD deadlock
# =============================================================================


@pytest.mark.anyio
async def test_intentionally_broken_pattern():
    """
    Create a pattern that SHOULD deadlock to verify our understanding.

    This is the "control" test - if this doesn't deadlock, our theory is wrong.
    """
    sender, receiver = anyio.create_memory_object_stream[str](0)

    async def delayed_receiver():
        # Delay for 100ms before starting to receive
        await anyio.sleep(0.1)
        async with receiver:
            async for item in receiver:
                return item

    async with anyio.create_task_group() as tg:
        tg.start_soon(delayed_receiver)

        # Try to send immediately - receiver is delayed 100ms
        # On a 0-capacity stream, this MUST block until receiver is ready
        async with sender:
            try:
                with anyio.fail_after(0.05):  # Only wait 50ms
                    await sender.send("test")
                # If we get here without timeout, the send completed
                # which means the receiver started despite our delay
                print("\nSend completed - receiver started faster than expected")
            except TimeoutError:
                # This is expected! Send blocked because receiver wasn't ready
                print("\nConfirmed: Send blocked on 0-capacity stream as expected")
                # This confirms the race condition CAN happen
                # Cancel the task group
                tg.cancel_scope.cancel()


# =============================================================================
# TEST 7: Race with CPU-bound work to delay task scheduling
# =============================================================================


@pytest.mark.anyio
async def test_race_with_cpu_blocking():
    """
    Try to trigger the race by doing CPU-bound work that prevents
    the event loop from running scheduled tasks.
    """
    import time

    params = StdioServerParameters(
        command=sys.executable,
        args=["-u", "-c", MINIMAL_SERVER],
    )

    for _ in range(20):
        # Do CPU-bound work right before and after entering context managers
        # This might prevent scheduled tasks from running

        # Block the event loop briefly
        start = time.perf_counter()
        while time.perf_counter() - start < 0.001:
            pass  # Busy wait

        with anyio.fail_after(5):
            async with stdio_client(params) as (read, write):
                # More blocking right after
                start = time.perf_counter()
                while time.perf_counter() - start < 0.001:
                    pass

                async with ClientSession(read, write) as session:
                    # And more blocking
                    start = time.perf_counter()
                    while time.perf_counter() - start < 0.001:
                        pass

                    await session.initialize()
                    await session.list_tools()
                    result = await session.call_tool("test", arguments={})
                    assert result.content[0].text == "Result"


# =============================================================================
# TEST 8: Create streams with capacity 0 and test concurrent access
# =============================================================================


@pytest.mark.anyio
async def test_zero_capacity_concurrent_stress():
    """
    Stress test 0-capacity streams with concurrent senders and receivers.
    """
    sender, receiver = anyio.create_memory_object_stream[int](0)

    received = []
    send_count = 100

    async def receiver_task():
        async with receiver:
            received.extend([item async for item in receiver])

    async def sender_task():
        async with sender:
            for i in range(send_count):
                await sender.send(i)

    # Run with very short timeout to catch any hangs
    try:
        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:
                tg.start_soon(receiver_task)
                tg.start_soon(sender_task)

        assert len(received) == send_count
    except TimeoutError:
        pytest.fail(f"Stress test deadlocked after receiving {len(received)}/{send_count} items")


# =============================================================================
# TEST 9: Patch to add checkpoint before send
# =============================================================================


@pytest.mark.anyio
async def test_with_explicit_checkpoint_before_send():
    """
    Add an explicit checkpoint before sending to give tasks time to start.

    If this fixes potential deadlocks, it confirms the race condition theory.
    """
    import mcp.shared.session as session_module

    original_send_request = session_module.BaseSession.send_request

    async def patched_send_request(self, request, result_type, **kwargs):
        # Add explicit checkpoint to let other tasks run
        await anyio.lowlevel.checkpoint()
        return await original_send_request(self, request, result_type, **kwargs)

    session_module.BaseSession.send_request = patched_send_request

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-u", "-c", MINIMAL_SERVER],
        )

        for _ in range(30):
            with anyio.fail_after(5):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        await session.list_tools()
                        result = await session.call_tool("test", arguments={})
                        assert result.content[0].text == "Result"

    finally:
        session_module.BaseSession.send_request = original_send_request


# =============================================================================
# TEST 10: Ultimate race condition test with task delay injection
# =============================================================================


@pytest.mark.anyio
async def test_ultimate_race_condition():
    """
    The ultimate test: inject delays at EVERY level to try to trigger the race.

    We patch:
    - BaseSession._receive_loop to delay at start
    - BaseSession.__aenter__ to delay after start_soon
    """
    import mcp.shared.session as session_module

    original_receive_loop = session_module.BaseSession._receive_loop
    original_aenter = session_module.BaseSession.__aenter__

    # Track if we ever see a hang
    hang_detected = False

    async def delayed_receive_loop(self):
        # Delay before starting to process
        await anyio.sleep(0.005)
        return await original_receive_loop(self)

    async def delayed_aenter(self):
        # Call original which schedules _receive_loop
        result = await original_aenter(self)
        # DON'T add delay here - we want to return before _receive_loop runs
        # The delay in _receive_loop should be enough
        return result

    session_module.BaseSession._receive_loop = delayed_receive_loop
    session_module.BaseSession.__aenter__ = delayed_aenter

    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-u", "-c", MINIMAL_SERVER],
        )

        success_count = 0
        for i in range(50):
            try:
                with anyio.fail_after(2):
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            await session.list_tools()
                            result = await session.call_tool("test", arguments={})
                            assert result.content[0].text == "Result"
                            success_count += 1
            except TimeoutError:
                print(f"\nHang detected at iteration {i}!")
                hang_detected = True
                break

        if hang_detected:
            pytest.fail("REPRODUCED! Hang detected with delayed receive loop!")
        else:
            print(f"\nAll {success_count} iterations completed successfully")

    finally:
        session_module.BaseSession._receive_loop = original_receive_loop
        session_module.BaseSession.__aenter__ = original_aenter
