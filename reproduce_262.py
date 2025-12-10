#!/usr/bin/env python3
"""
Minimal reproduction of issue #262: MCP Client Tool Call Hang

This script demonstrates the race condition that causes call_tool() to hang.
Run with: python reproduce_262.py

The bug is caused by:
1. Zero-capacity memory streams (anyio.create_memory_object_stream(0))
2. Tasks started with start_soon() (not awaited)
3. Immediate send after context manager enters

When the receiver task hasn't started yet, send() blocks forever.

See: https://github.com/modelcontextprotocol/python-sdk/issues/262
"""

import anyio


async def demonstrate_bug():
    """Reproduce the exact race condition that causes issue #262."""

    print("=" * 60)
    print("Issue #262 Reproduction: Zero-buffer + start_soon race condition")
    print("=" * 60)

    # Create zero-capacity stream - sender blocks until receiver is ready
    sender, receiver = anyio.create_memory_object_stream[str](0)

    receiver_started = False

    async def delayed_receiver():
        nonlocal receiver_started
        # Simulate the delay that occurs in real code when tasks
        # are scheduled with start_soon but haven't started yet
        await anyio.sleep(0.05)  # 50ms delay
        receiver_started = True
        async with receiver:
            async for item in receiver:
                print(f"  Received: {item}")
                return

    print("\n1. Creating zero-capacity stream (like stdio_client lines 117-118)")
    print("2. Starting receiver with start_soon (like stdio_client lines 186-187)")
    print("3. Immediately trying to send (like session.send_request)")
    print()

    async with anyio.create_task_group() as tg:
        # Start receiver with start_soon - NOT awaited!
        # This is exactly what stdio_client does
        tg.start_soon(delayed_receiver)

        # Try to send immediately - receiver is delayed 50ms
        async with sender:
            print("Attempting to send...")
            print(f"  Receiver started yet? {receiver_started}")

            try:
                # Only wait 20ms - less than the 50ms receiver delay
                with anyio.fail_after(0.02):
                    await sender.send("Hello")
                    print("  Send completed (receiver was fast)")
            except TimeoutError:
                print()
                print("  *** REPRODUCTION SUCCESSFUL! ***")
                print("  Send BLOCKED because receiver wasn't ready!")
                print(f"  Receiver started: {receiver_started}")
                print()
                print("  This is EXACTLY what happens in issue #262:")
                print("  - call_tool() sends a request")
                print("  - The receive loop hasn't started yet")
                print("  - Send blocks forever on the zero-capacity stream")
                print()

                # Cancel to clean up
                tg.cancel_scope.cancel()


async def demonstrate_fix_buffer():
    """Show that using buffer > 0 fixes the issue."""

    print("\n" + "=" * 60)
    print("FIX #1: Use buffer size > 0")
    print("=" * 60)

    # Buffer size 1 instead of 0
    sender, receiver = anyio.create_memory_object_stream[str](1)

    async def delayed_receiver():
        await anyio.sleep(0.05)  # Same 50ms delay
        async with receiver:
            async for item in receiver:
                print(f"  Received: {item}")
                return

    async with anyio.create_task_group() as tg:
        tg.start_soon(delayed_receiver)

        async with sender:
            print("Attempting to send with buffer=1...")
            try:
                with anyio.fail_after(0.01):  # Only 10ms timeout
                    await sender.send("Hello")
                    print("  SUCCESS! Send completed immediately")
                    print("  Buffer allows send without blocking on receiver")
            except TimeoutError:
                print("  Still blocked (unexpected)")


async def demonstrate_fix_start():
    """Show that using start() instead of start_soon() fixes the issue."""

    print("\n" + "=" * 60)
    print("FIX #2: Use await tg.start() instead of tg.start_soon()")
    print("=" * 60)

    sender, receiver = anyio.create_memory_object_stream[str](0)

    async def receiver_with_signal(*, task_status=anyio.TASK_STATUS_IGNORED):
        # Signal that we're ready BEFORE starting to receive
        task_status.started()
        async with receiver:
            async for item in receiver:
                print(f"  Received: {item}")
                return

    async with anyio.create_task_group() as tg:
        # Use start() - this WAITS for task_status.started()
        await tg.start(receiver_with_signal)

        async with sender:
            print("Attempting to send after start()...")
            try:
                with anyio.fail_after(0.01):
                    await sender.send("Hello")
                    print("  SUCCESS! Send completed immediately")
                    print("  start() ensures receiver is ready before continuing")
            except TimeoutError:
                print("  Still blocked (unexpected)")


async def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║  Issue #262: MCP Client Tool Call Hang - Minimal Reproduction ║
╚══════════════════════════════════════════════════════════════╝
""")

    try:
        await demonstrate_bug()
    except anyio.get_cancelled_exc_class():
        pass

    await demonstrate_fix_buffer()
    await demonstrate_fix_start()

    print("\n" + "=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    print("""
The bug in stdio_client (src/mcp/client/stdio/__init__.py):

  Lines 117-118:
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)  # BUG: 0!
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)  # BUG: 0!

  Lines 186-187:
    tg.start_soon(stdout_reader)  # BUG: Not awaited!
    tg.start_soon(stdin_writer)   # BUG: Not awaited!

FIX OPTIONS:
  1. Change buffer from 0 to 1: anyio.create_memory_object_stream(1)
  2. Use await tg.start() instead of tg.start_soon()
""")


if __name__ == "__main__":
    anyio.run(main)
