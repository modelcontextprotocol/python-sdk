# Issue #262 Investigation Notes

## Problem Statement
`session.call_tool()` hangs indefinitely while `session.list_tools()` works fine.
The server executes successfully and produces results, but the client cannot receive them.

## Key Observations from Issue
- Debugger stepping makes issue disappear (timing/race condition)
- Works on native Windows, fails on WSL Ubuntu
- Affects both stdio and SSE transports
- Server produces output but client doesn't receive it

## Related Issues

### Issue #1764 - CRITICAL INSIGHT!
**Problem:** Race condition in StreamableHTTPServerTransport with SSE connections hanging.

**Root Cause:** Zero-buffer memory streams + `tg.start_soon()` pattern causes deadlock:
- `send()` blocks until `receive()` is called on zero-buffer streams
- When sender is faster than receiver task initializes, deadlock occurs
- Responses with 1-2 items work, 3+ items deadlock (timing dependent!)

**Fix:** Either increase buffer size OR use `await tg.start()` to ensure receiver ready.

**Relevance to #262:** The `stdio_client` uses EXACTLY this pattern:
```python
read_stream_writer, read_stream = anyio.create_memory_object_stream(0)  # Zero buffer!
write_stream, write_stream_reader = anyio.create_memory_object_stream(0)  # Zero buffer!
# ...
tg.start_soon(stdout_reader)  # Not awaited!
tg.start_soon(stdin_writer)   # Not awaited!
```

This could cause the exact hang described in #262 if the server responds before
the client's receive loop is ready to receive!

## Comprehensive Test Results

### Test Categories and Results

| Category | Tests | Result | Notes |
|----------|-------|--------|-------|
| Basic tool call | 1 | PASS | Simple scenario works |
| Buffering tests | 3 | PASS | Flush/no-flush, unbuffered all work |
| 0-capacity streams | 3 | PASS | Rapid responses, notifications work |
| Interleaved notifications | 2 | PASS | Server notifications during tool work |
| Sampling during tool | 1 | PASS | Bidirectional communication works |
| Timing races | 2 | PASS | Small delays don't trigger |
| Big delays (2-3 sec) | 1 | PASS | Server delays don't cause hang |
| Instant response | 1 | PASS | Immediate response works |
| Burst responses | 1 | PASS | 20 rapid log messages handled |
| Slow callbacks | 2 | PASS | Slow logging/message handlers work |
| Many iterations | 1 | PASS | 50 rapid iterations all succeed |
| Concurrent sessions | 2 | PASS | Multiple parallel sessions work |
| Stress tests | 2 | PASS | 30 sequential sessions work |
| Patched SDK | 3 | PASS | Delays in SDK don't trigger |
| CPU pressure | 1 | PASS | Heavy CPU load doesn't trigger |
| Raw subprocess | 2 | PASS | Direct pipe communication works |
| Preemptive response | 1 | PASS | Unbuffered immediate response works |

**Total: 34 tests, all passing**

### Theories Tested

1. **Stdout Buffering** - Server not flushing stdout after responses
   - Result: NOT the cause - works with and without flush

2. **0-Capacity Streams** - stdio_client uses unbuffered streams (capacity 0)
   - Result: NOT the cause on this platform - works in test environment

3. **Interleaved Notifications** - Server sending log notifications during tool execution
   - Result: NOT the cause - notifications handled correctly

4. **Bidirectional Communication** - Server requesting sampling during tool execution
   - Result: NOT the cause - bidirectional works

5. **Timing/Race Conditions** - Small delays in server response
   - Result: Could not reproduce with various delay patterns

6. **Big Delays (2-3 seconds)** - As comments suggest
   - Result: NOT the cause - big delays work fine

7. **Slow Callbacks** - Message handler/logging callback that blocks
   - Result: NOT the cause - slow callbacks work

8. **Zero-buffer + start_soon race** (from #1764)
   - Result: Could not reproduce, but this remains the most likely cause

9. **CPU Pressure** - Heavy CPU load exposing timing issues
   - Result: NOT the cause on this platform

10. **Raw Subprocess Communication** - Direct pipe handling
    - Result: Works correctly, issue is not in pipe handling

## Environment Notes
- Testing on: Linux (not WSL)
- Python: 3.11.14
- Using anyio for async
- All 34 tests pass consistently

## Conclusions

### Why We Cannot Reproduce
The issue appears to be **highly environment-specific**:
1. **WSL-specific behavior** - The original reporter experienced this on WSL Ubuntu, not native Linux/Windows
2. **Timing-dependent** - Debugger stepping makes it disappear, suggesting a very narrow timing window
3. **Platform-specific pipe behavior** - WSL has different I/O characteristics than native Linux

### Most Likely Root Cause
Based on issue #1764, the most likely cause is the **zero-buffer memory stream + start_soon pattern**:
1. `stdio_client` creates 0-capacity streams
2. Reader/writer tasks are started with `start_soon` (not awaited)
3. In certain environments (WSL), the timing allows responses to arrive before the receive loop is ready
4. This causes the send to block indefinitely (deadlock)

### Potential Fixes (to be verified on WSL)
1. **Increase stream buffer size** - Change from `anyio.create_memory_object_stream(0)` to `anyio.create_memory_object_stream(1)` or higher
2. **Use `await tg.start()`** - Ensure receive loop is ready before returning from context manager
3. **Add synchronization** - Use an Event to signal when receive loop is ready

## Files Created
- `tests/issues/test_262_tool_call_hang.py` - Comprehensive test suite (34 tests)
- `tests/issues/reproduce_262_standalone.py` - Standalone reproduction script
- `ISSUE_262_INVESTIGATION.md` - This investigation document

## Recommendations
1. **For users experiencing this issue:**
   - Try running on native Linux or Windows instead of WSL
   - Check if adding a small delay after session creation helps

2. **For maintainers:**
   - Consider changing stream buffer size in `stdio_client` from 0 to 1
   - Consider using `await tg.start()` pattern instead of `start_soon` for critical tasks
   - Test changes specifically on WSL Ubuntu to verify fix

3. **For further investigation:**
   - Need WSL Ubuntu environment to reproduce
   - Could try patching `stdio_client` to use `anyio.create_memory_object_stream(1)` and test
