#!/usr/bin/env python3
"""
Investigation script for issue #262: MCP Client Tool Call Hang

This script investigates the potential race condition related to:
1. Zero-capacity memory streams (anyio.create_memory_object_stream(0))
2. Tasks started with start_soon() (not awaited)

WHAT THIS SCRIPT SHOWS:
- With zero-capacity streams, send() blocks until receive() is called
- If the receiver task hasn't started its receive loop yet, send() waits
- We can detect this blocking using short timeouts

WHAT THIS SCRIPT DOES NOT SHOW:
- We could NOT reproduce a permanent hang on this Linux system
- We do NOT know if WSL's scheduler actually causes permanent hangs
- We do NOT know if this is the actual cause of issue #262

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
"""

import anyio


async def demonstrate_temporary_blocking():
    """
    Demonstrate that send() blocks when receiver isn't ready.

    This uses a short timeout to DETECT blocking, not to cause it.
    The blocking is temporary because Python's cooperative async
    eventually runs the receiver task.
    """
    print("=" * 70)
    print("Test: Does send() block when receiver isn't ready?")
    print("=" * 70)
    print()

    # Create zero-capacity stream - sender blocks until receiver is ready
    sender, receiver = anyio.create_memory_object_stream[str](0)

    receiver_entered_loop = anyio.Event()

    async def delayed_receiver():
        """Receiver that has a delay before entering its receive loop."""
        await anyio.sleep(0.1)  # 100ms delay before entering receive loop
        receiver_entered_loop.set()
        async with receiver:
            async for item in receiver:
                print(f"  [Receiver] Got: {item}")
                return

    print("Setup:")
    print("  - Zero-capacity stream (send blocks until receive)")
    print("  - Receiver has 100ms delay before entering receive loop")
    print("  - Sender uses 50ms timeout (shorter than receiver delay)")
    print()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(delayed_receiver)

            async with sender:
                print(f"  [Sender] receiver_entered_loop = {receiver_entered_loop.is_set()}")
                print("  [Sender] Attempting to send...")

                try:
                    with anyio.fail_after(0.05):  # 50ms timeout
                        await sender.send("Hello")
                        print("  [Sender] Send completed within 50ms")
                except TimeoutError:
                    print()
                    print("  RESULT: send() blocked for >50ms")
                    print(f"  receiver_entered_loop = {receiver_entered_loop.is_set()}")
                    print()
                    print("  This shows that send() waits for receiver to be ready.")
                    print("  On this system, the blocking is temporary (cooperative async).")
                    tg.cancel_scope.cancel()

    except anyio.get_cancelled_exc_class():
        pass

    print()


async def demonstrate_fix_buffer():
    """Show that using buffer > 0 prevents blocking."""
    print("=" * 70)
    print("Fix #1: Use buffer size > 0")
    print("=" * 70)
    print()

    # Buffer size 1 instead of 0
    sender, receiver = anyio.create_memory_object_stream[str](1)

    async def delayed_receiver():
        await anyio.sleep(0.1)  # Same 100ms delay
        async with receiver:
            async for item in receiver:
                print(f"  [Receiver] Got: {item}")
                return

    async with anyio.create_task_group() as tg:
        tg.start_soon(delayed_receiver)

        async with sender:
            print("  [Sender] Sending with buffer=1...")
            try:
                with anyio.fail_after(0.01):  # Only 10ms timeout
                    await sender.send("Hello with buffer!")
                    print("  [Sender] Send completed within 10ms")
                    print("  Buffer allows send to complete without waiting for receiver")
            except TimeoutError:
                print("  Unexpected: still blocked")

    print()


async def demonstrate_fix_start():
    """Show that using start() instead of start_soon() guarantees receiver is ready."""
    print("=" * 70)
    print("Fix #2: Use await tg.start() instead of tg.start_soon()")
    print("=" * 70)
    print()

    sender, receiver = anyio.create_memory_object_stream[str](0)

    async def receiver_with_signal(*, task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started()  # Signal ready BEFORE entering receive loop
        async with receiver:
            async for item in receiver:
                print(f"  [Receiver] Got: {item}")
                return

    async with anyio.create_task_group() as tg:
        # start() waits for task_status.started()
        await tg.start(receiver_with_signal)

        async with sender:
            print("  [Sender] Sending after start() returned...")
            try:
                with anyio.fail_after(0.01):
                    await sender.send("Hello with start()!")
                    print("  [Sender] Send completed within 10ms")
                    print("  start() guarantees receiver is ready before we continue")
            except TimeoutError:
                print("  Unexpected: still blocked")

    print()


async def main():
    print("""
======================================================================
Issue #262 Investigation: Zero-capacity streams + start_soon()
======================================================================

This script investigates whether zero-capacity streams combined with
start_soon() can cause blocking.

NOTE: We could NOT reproduce a permanent hang on this Linux system.
The blocking we observe is temporary - Python's cooperative async
eventually runs the receiver. Whether this causes permanent hangs
on other systems (like WSL) is unknown.
""")

    await demonstrate_temporary_blocking()
    await demonstrate_fix_buffer()
    await demonstrate_fix_start()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("""
OBSERVED:
  - send() on zero-capacity stream blocks until receiver is ready
  - If receiver task has a delay, send() waits
  - On this system, blocking is temporary (cooperative async works)

NOT OBSERVED:
  - Permanent hang (could not reproduce)
  - WSL-specific behavior (not tested on WSL)

POTENTIAL FIXES (untested against actual hang):
  1. Change buffer from 0 to 1
  2. Use start() instead of start_soon()

NEXT STEPS:
  - Test on WSL to see if permanent hang occurs
  - Get more details from users who experienced the hang
""")


if __name__ == "__main__":
    anyio.run(main)
