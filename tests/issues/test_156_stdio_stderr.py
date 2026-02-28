"""Regression test for issue #156: Jupyter Notebook stderr logging.

When running in Jupyter, stderr from subprocess servers isn't visible because
Jupyter doesn't display stderr output directly.  The fix pipes stderr via
subprocess.PIPE and adds a reader task that detects Jupyter and uses print()
with ANSI red colouring.
"""

import sys
import textwrap

import anyio
import pytest

from mcp.client.stdio import StdioServerParameters, stdio_client

# A minimal MCP-like server that writes to stderr and then exits.
SERVER_SCRIPT = textwrap.dedent("""\
    import sys
    sys.stderr.write("hello from stderr\\n")
    sys.stderr.flush()
    # Read stdin until EOF so the process doesn't exit before client reads stderr
    sys.stdin.read()
""")


@pytest.mark.anyio
async def test_stderr_is_captured(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that subprocess stderr is captured and printed to errlog (sys.stderr)."""
    from unittest.mock import patch

    params = StdioServerParameters(command=sys.executable, args=["-c", SERVER_SCRIPT])

    # Force is_jupyter=False so we use the standard errlog path
    # Pass sys.stderr explicitly so we use the capsys-patched stderr
    with patch("mcp.client.stdio.is_jupyter", return_value=False), anyio.fail_after(10):
        async with stdio_client(params, errlog=sys.stderr) as (_read, _write):
            # Give the stderr_reader task time to process
            await anyio.sleep(0.5)

    captured = capsys.readouterr()
    # verify it went to stderr
    assert "hello from stderr" in captured.err


@pytest.mark.anyio
async def test_stderr_is_routed_to_errlog() -> None:
    """Verify that subprocess stderr is written to the provided explicit errlog."""
    import io
    from unittest.mock import patch

    errlog = io.StringIO()
    params = StdioServerParameters(command=sys.executable, args=["-c", SERVER_SCRIPT])

    with patch("mcp.client.stdio.is_jupyter", return_value=False), anyio.fail_after(10):
        async with stdio_client(params, errlog=errlog) as (_read, _write):
            await anyio.sleep(0.5)

    assert "hello from stderr" in errlog.getvalue()


@pytest.mark.anyio
async def test_stderr_is_printed_with_color_in_jupyter(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify that subprocess stderr is printed with ANSI red in Jupyter."""
    from unittest.mock import patch

    params = StdioServerParameters(command=sys.executable, args=["-c", SERVER_SCRIPT])

    # Force is_jupyter=True so we use the print() path
    with patch("mcp.client.stdio.is_jupyter", return_value=True), anyio.fail_after(10):
        async with stdio_client(params) as (_read, _write):
            await anyio.sleep(0.5)

    captured = capsys.readouterr()
    # print() goes to stdout by default
    assert "\033[91mhello from stderr" in captured.out
