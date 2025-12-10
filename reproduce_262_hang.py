#!/usr/bin/env python3
"""
Issue #262 Reproduction: TRUE Hang Scenario

This script demonstrates the EXACT race condition that causes permanent hangs.
Unlike the normal reproduction which uses timeouts to PROVE the race exists,
this script creates conditions that ACTUALLY hang.

The key insight is that the race condition doesn't hang due to Python's
cooperative async (blocking yields control). The hang happens because:

1. Zero-capacity streams require synchronous rendezvous
2. When the receiver task hasn't started its receive loop yet, send() waits
3. In specific conditions (WSL scheduler quirks), the receiver never runs

To SIMULATE this in a portable way, we use synchronization primitives to
PREVENT the receiver from entering its receive loop until after the sender
times out - proving that without synchronization, this is a deadlock.

Usage:
  python reproduce_262_hang.py          # Normal mode - shows race
  python reproduce_262_hang.py hang     # ACTUALLY hangs (Ctrl+C to exit)
"""

import sys

import anyio


async def reproduce_with_race():
    """
    Demonstrate the race condition that WOULD cause a hang if the scheduler
    didn't eventually run the receiver.

    This shows the exact problem: send() on a zero-capacity stream blocks
    until receive() is called, but with start_soon(), receive() may not be
    running yet.
    """
    print("=" * 70)
    print("Issue #262: Race Condition Demonstration")
    print("=" * 70)
    print()
    print("Creating the EXACT scenario from stdio_client:")
    print("  1. Zero-capacity memory streams")
    print("  2. Receiver started with start_soon() (not awaited)")
    print("  3. Sender immediately tries to send")
    print()

    # Zero-capacity streams - exactly like stdio_client lines 117-118
    sender, receiver = anyio.create_memory_object_stream[str](0)

    receiver_in_loop = anyio.Event()
    sent = anyio.Event()

    async def receiver_task():
        """Simulates the stdin_writer task in stdio_client."""
        # Add a small delay to simulate task scheduling overhead
        # In real code, this is the time between start_soon() and the task running
        await anyio.sleep(0.01)

        print("[Receiver] Entering receive loop...")
        receiver_in_loop.set()

        async with receiver:
            async for msg in receiver:
                print(f"[Receiver] Got message: {msg}")
                return

    async def sender_task():
        """Simulates session.send_request() in ClientSession."""
        async with sender:
            # Check if receiver is ready - this is the race!
            print(f"[Sender] Receiver in loop? {receiver_in_loop.is_set()}")
            print("[Sender] Sending message...")

            # This is where the race manifests:
            # - If receiver is in its loop: send() completes immediately
            # - If receiver NOT in loop: send() blocks until receiver starts
            # - On WSL with scheduler quirks: receiver may NEVER start
            await sender.send("Hello, Issue #262!")
            print("[Sender] Message sent!")
            sent.set()

    async with anyio.create_task_group() as tg:
        # Start receiver with start_soon - not awaited!
        # This is EXACTLY what stdio_client does
        tg.start_soon(receiver_task)

        # Immediately start sender - this races with receiver
        tg.start_soon(sender_task)

        # Wait for both to complete
        with anyio.move_on_after(2.0) as scope:
            await sent.wait()

        if scope.cancelled_caught:
            print()
            print("RACE CONDITION: Sender took > 2s!")
            print("This would be a permanent hang on WSL.")
            tg.cancel_scope.cancel()
        else:
            print()
            print("Race completed (cooperative scheduling worked)")

    print()


async def reproduce_actual_hang():
    """
    Create a TRUE hang by preventing the receiver from ever entering its loop.

    This simulates what happens on WSL: the scheduler never runs the receiver
    task while the sender is blocked on send().

    WARNING: This WILL hang. Use Ctrl+C to exit.
    """
    print("=" * 70)
    print("Issue #262: ACTUAL HANG DEMONSTRATION")
    print("=" * 70)
    print()
    print("WARNING: This WILL hang permanently. Press Ctrl+C to exit.")
    print()
    print("This demonstrates what happens on WSL:")
    print("  - Receiver task is scheduled but never runs")
    print("  - Sender blocks on zero-capacity stream")
    print("  - No one receives, so sender waits forever")
    print()

    sender, receiver = anyio.create_memory_object_stream[str](0)

    receiver_blocked = anyio.Event()
    allow_receiver = anyio.Event()

    async def blocked_receiver():
        """
        Simulates a receiver that's scheduled but hasn't started its receive loop.

        On WSL, this happens because the scheduler doesn't run this task.
        Here, we explicitly block to simulate that behavior.
        """
        print("[Receiver] Task started, but blocking before receive loop...")
        receiver_blocked.set()

        # This simulates WSL's scheduler not running this task
        # The receiver is SCHEDULED but never actually runs its receive loop
        await allow_receiver.wait()  # Will NEVER be set = hangs forever

        print("[Receiver] This will never print!")
        async with receiver:
            async for msg in receiver:
                print(f"[Receiver] Got: {msg}")

    async def hanging_sender():
        """Sender that will hang because receiver never enters its loop."""
        async with sender:
            # Wait for receiver task to start (but not enter its loop)
            await receiver_blocked.wait()

            print("[Sender] Receiver task started but NOT in receive loop")
            print("[Sender] Attempting send on zero-capacity stream...")
            print("[Sender] This will hang forever (simulating WSL)")
            print()

            # This will NEVER complete because receiver is not in its loop
            await sender.send("This will never be received")

            print("[Sender] This will never print!")

    print("Starting tasks...")
    print()

    async with anyio.create_task_group() as tg:
        tg.start_soon(blocked_receiver)
        tg.start_soon(hanging_sender)

        # Never completes - hangs forever


async def demonstrate_fix():
    """Show that using buffer=1 fixes the hang."""
    print("=" * 70)
    print("FIX: Using buffer=1 prevents the hang")
    print("=" * 70)
    print()

    # Buffer of 1 instead of 0
    sender, receiver = anyio.create_memory_object_stream[str](1)

    receiver_blocked = anyio.Event()
    allow_receiver = anyio.Event()
    send_completed = anyio.Event()

    async def blocked_receiver():
        receiver_blocked.set()
        await allow_receiver.wait()
        async with receiver:
            async for msg in receiver:
                print(f"[Receiver] Got: {msg}")
                return

    async def sender_with_buffer():
        async with sender:
            await receiver_blocked.wait()
            print("[Sender] Receiver task not in loop, but buffer=1...")
            await sender.send("This goes into the buffer!")
            print("[Sender] Send completed immediately (buffer=1)")
            send_completed.set()
            # Now let receiver run
            allow_receiver.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(blocked_receiver)
        tg.start_soon(sender_with_buffer)

    print()
    print("With buffer=1, send() completes even before receiver is ready!")
    print()


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "race"

    print("""
╔════════════════════════════════════════════════════════════════════╗
║  Issue #262: MCP Client Tool Call Hang                             ║
║                                                                    ║
║  Usage:                                                            ║
║    python reproduce_262_hang.py        # Show race condition       ║
║    python reproduce_262_hang.py hang   # ACTUAL hang (Ctrl+C)      ║
║    python reproduce_262_hang.py fix    # Show the fix              ║
╚════════════════════════════════════════════════════════════════════╝
""")

    if mode == "hang":
        await reproduce_actual_hang()
    elif mode == "fix":
        await demonstrate_fix()
    else:
        await reproduce_with_race()
        await demonstrate_fix()

        print("=" * 70)
        print("CONCLUSION")
        print("=" * 70)
        print("""
The race condition in stdio_client:

  1. Zero-capacity streams require send/receive rendezvous
  2. start_soon() schedules tasks but doesn't wait for them
  3. If receiver isn't in its loop when send() is called, sender blocks
  4. On WSL, scheduler quirks prevent receiver from ever running

The fix is simple: change buffer from 0 to 1:
  anyio.create_memory_object_stream(1)

This allows send() to complete immediately (into the buffer) without
waiting for the receiver to be ready.

To see an ACTUAL hang, run: python reproduce_262_hang.py hang
""")


if __name__ == "__main__":
    anyio.run(main)
