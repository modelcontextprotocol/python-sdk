"""
Minimal reproduction of issue #262: MCP Client Tool Call Hang

This file contains the simplest possible reproduction of the race condition
that causes call_tool() to hang.

The root cause is the combination of:
1. Zero-capacity memory streams (anyio.create_memory_object_stream(0))
2. Tasks started with start_soon (not awaited to ensure they're running)
3. Immediate send after context manager enters

When these conditions align, send blocks forever because the receiver
task hasn't started yet.
"""

import anyio
import pytest


@pytest.mark.anyio
async def test_minimal_race_condition_reproduction():
    """
    The simplest possible reproduction of the race condition.

    Pattern:
    - Create 0-capacity stream
    - Start receiver with start_soon + delay at receiver start
    - Immediately try to send

    This WILL block if the receiver delay is long enough.
    """
    # Create 0-capacity stream - sender blocks until receiver is ready
    sender, receiver = anyio.create_memory_object_stream[str](0)

    received_items = []
    receiver_started = False

    async def delayed_receiver():
        nonlocal receiver_started
        # This delay simulates the race: receiver isn't ready immediately
        await anyio.sleep(0.05)  # 50ms delay
        receiver_started = True
        try:
            async with receiver:
                async for item in receiver:
                    received_items.append(item)
        except anyio.ClosedResourceError:
            pass

    try:
        async with anyio.create_task_group() as tg:
            # Start receiver with start_soon - NOT awaited!
            tg.start_soon(delayed_receiver)

            # Try to send IMMEDIATELY
            # The receiver has a 50ms delay, so it's NOT ready
            # On a 0-capacity stream, this MUST block until receiver is ready
            async with sender:
                try:
                    with anyio.fail_after(0.02):  # Only wait 20ms (less than receiver delay)
                        await sender.send("test")
                        # If we get here, receiver started faster than expected
                        print(f"Send completed. Receiver started: {receiver_started}")
                except TimeoutError:
                    # EXPECTED! This proves the race condition exists
                    print(f"REPRODUCED: Send blocked because receiver wasn't ready!")
                    print(f"Receiver started: {receiver_started}")

                    # This is the reproduction!
                    # In issue #262, this manifests as call_tool() hanging forever

                    # Cancel to clean up
                    tg.cancel_scope.cancel()
                    return

    except anyio.get_cancelled_exc_class():
        pass

    # If we get here without timing out, the race wasn't triggered
    print(f"Race not triggered this time. Received: {received_items}")


@pytest.mark.anyio
async def test_demonstrate_fix_with_buffer():
    """
    Demonstrate that using a buffer > 0 fixes the issue.

    With buffer size 1, send doesn't block even if receiver isn't ready.
    """
    # Buffer size 1 instead of 0
    sender, receiver = anyio.create_memory_object_stream[str](1)

    async def delayed_receiver():
        await anyio.sleep(0.05)  # 50ms delay
        async with receiver:
            async for item in receiver:
                print(f"Received: {item}")

    async with anyio.create_task_group() as tg:
        tg.start_soon(delayed_receiver)

        async with sender:
            # This should NOT block even though receiver is delayed
            with anyio.fail_after(0.01):  # Only 10ms timeout
                await sender.send("test")
                print("Send completed immediately with buffer!")


@pytest.mark.anyio
async def test_demonstrate_fix_with_start():
    """
    Demonstrate that using start() instead of start_soon() fixes the issue.

    With start(), we wait for the task to be ready before continuing.
    """
    sender, receiver = anyio.create_memory_object_stream[str](0)

    async def receiver_with_start(*, task_status=anyio.TASK_STATUS_IGNORED):
        # Signal that we're ready to receive
        task_status.started()

        async with receiver:
            async for item in receiver:
                print(f"Received: {item}")

    async with anyio.create_task_group() as tg:
        # Use start() instead of start_soon() - this waits for task_status.started()
        await tg.start(receiver_with_start)

        async with sender:
            # Now send is guaranteed to work because receiver is ready
            with anyio.fail_after(0.01):
                await sender.send("test")
                print("Send completed with start()!")


@pytest.mark.anyio
async def test_many_iterations_to_catch_race():
    """
    Run many iterations to try to catch the race condition.

    Even without explicit delays, the race might occur naturally.
    """
    success = 0
    blocked = 0
    iterations = 100

    for _ in range(iterations):
        sender, receiver = anyio.create_memory_object_stream[str](0)

        async def receiver_task():
            async with receiver:
                async for item in receiver:
                    return item

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(receiver_task)

                async with sender:
                    try:
                        with anyio.fail_after(0.001):  # Very short timeout
                            await sender.send("test")
                            success += 1
                    except TimeoutError:
                        blocked += 1
                        tg.cancel_scope.cancel()

        except anyio.get_cancelled_exc_class():
            pass

    print(f"\nResults: {success} succeeded, {blocked} blocked out of {iterations}")

    # If ANY blocked, the race condition exists
    if blocked > 0:
        print(f"RACE CONDITION CONFIRMED: {blocked}/{iterations} sends blocked!")
