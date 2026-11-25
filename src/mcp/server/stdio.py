"""Stdio server transport for MCP.

Example:
    ```python
    async def run_server():
        async with stdio_server() as (read_stream, write_stream):
            server = await create_my_server()
            await server.run(read_stream, write_stream, init_options)

    anyio.run(run_server)
    ```
"""

import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from io import TextIOWrapper
from typing import Any, BinaryIO, Final, Literal, TextIO, cast

import anyio
import anyio.lowlevel
import mcp_types as types
import pydantic_core

from mcp.os.win32.utilities import rebind_std_handle_to_fd
from mcp.shared._context_streams import create_context_streams
from mcp.shared._stream_protocols import WriteStream
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

if sys.platform != "win32":  # pragma: no branch
    import fcntl  # pragma: lax no cover - POSIX-only line, uncovered on Windows runners

# Stream-claim contract (design and attack log in PR #3117):
# - _claims is the single authority for who owns fd 0/1; mutated only under the
#   lock, only by acquire's insert and release's deregister.
# - private_fd is recorded the instant the wire duplicate exists, before fd is
#   ever moved, and is never closed while the claim is registered.
# - Release deregisters only after dup2(private_fd, fd) restores the wire; a
#   failed release keeps the claim, so successors are refused, never fed a
#   diverted descriptor. Every failure lands on that safe side.
_claims: dict[int, "_StreamClaim"] = {}
_claims_lock = threading.Lock()


@dataclass
class _StreamClaim:
    fd: int
    private_fd: int | None = None


class _UnownedTextWrapper(TextIOWrapper):
    """Text layer whose close never closes the underlying buffer.

    The buffer is not the transport's to close: in the in-place paths it is the
    sys stream's own buffer, and closing it at garbage collection destroyed
    sys.stdout for the rest of the process (issue #1933).
    """

    def close(self) -> None:
        with suppress(ValueError):
            self.detach()


def _is_backed_by_fd(stream: TextIO, fd: int) -> bool:
    try:
        return stream.buffer.fileno() == fd
    except (AttributeError, OSError, ValueError):
        return False


def _dup_above_std(fd: int) -> int:
    """Duplicate fd onto a descriptor that cannot land in the standard range."""
    if sys.platform == "win32":  # pragma: no cover
        duplicate = os.dup(fd)
        if duplicate <= 2:
            os.close(duplicate)
            raise OSError(f"duplicate of fd {fd} landed in the standard range")
        return duplicate
    return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)  # pragma: lax no cover - POSIX-only


def _open_stdin_diversion() -> int:
    return os.open(os.devnull, os.O_RDONLY)


def _open_stdout_diversion() -> int:
    try:
        return os.dup(2)
    except OSError:
        return os.open(os.devnull, os.O_WRONLY)


def _restore_fd(fd: int, private_fd: int) -> bool:
    """Point fd back at the wire; the Windows handle rebind never affects the outcome."""
    try:
        os.dup2(private_fd, fd)
    except OSError:
        return False
    if sys.platform == "win32":  # pragma: no cover
        with suppress(OSError):
            rebind_std_handle_to_fd(fd)
    return True


def _claim_fd(
    fd: int, stream: TextIO, mode: Literal["rb", "wb"], open_diversion: Callable[[], int]
) -> tuple[BinaryIO, Callable[[], None] | None]:
    """Claim a standard stream: divert fd and serve the wire from a private duplicate.

    Best-effort: when descriptors cannot be duplicated or diverted, serves the
    sys stream's buffer in place, exactly as v1 did, with the claim held.

    Raises:
        RuntimeError: fd is already claimed by another transport in this process.
    """
    if not _is_backed_by_fd(stream, fd):
        return stream.buffer, None
    claim = _StreamClaim(fd)
    with _claims_lock:
        if fd in _claims:
            raise RuntimeError(f"another stdio_server() in this process has already claimed fd {fd}")
        _claims[fd] = claim

    def release() -> None:
        if claim.private_fd is None or _restore_fd(fd, claim.private_fd):
            with _claims_lock:
                del _claims[fd]

    try:
        private_fd = _dup_above_std(fd)
    except OSError:
        return stream.buffer, release
    claim.private_fd = private_fd

    try:
        diversion_fd = open_diversion()
    except OSError:
        return stream.buffer, release
    try:
        os.dup2(diversion_fd, fd)
    except OSError:
        # The divert did not land; ensure fd carries the wire (a Windows dup2 can
        # close its target before failing), then serve it in place through the
        # shared buffer, since two writers on one pipe would tear frames.
        with suppress(OSError):
            os.close(diversion_fd)
        _restore_fd(fd, private_fd)
        return stream.buffer, release
    with suppress(OSError):
        os.close(diversion_fd)
    if sys.platform == "win32":  # pragma: no cover
        with suppress(OSError):
            rebind_std_handle_to_fd(fd)

    # closefd=False: a worker thread can still block on this descriptor after
    # the transport exits, so it must never be closed and recycled under it.
    return os.fdopen(private_fd, mode, closefd=False), release


_PARSE_ERROR_MESSAGE: Final = "Parse error"
"""JSON-RPC 2.0 §5 wording for -32700: the line was not well-formed JSON."""

_INVALID_REQUEST_MESSAGE: Final = "Invalid Request"
"""JSON-RPC 2.0 §5 wording for -32600: well-formed JSON that is not one usable message."""


def _lenient_decode(line: str) -> Any:
    """Decode a line with Python's `json`, which tolerates what pydantic-core refuses.

    Used only to *identify* a line pydantic-core rejected, never to accept one:
    the engines disagree on invalid Unicode escapes. A lone surrogate such as
    `\\ud83d` - the escape `json.dumps(ensure_ascii=True)` writes for half of a
    sliced emoji - decodes under `json` and is refused by pydantic-core, so
    `json` still yields the envelope, and with it the id the client awaits.

    Returns the decoded value, or `None` when even `json` cannot parse the line.
    """
    try:
        return json.loads(line)
    except (ValueError, RecursionError):
        # Not just JSONDecodeError: oversized integer literals raise bare
        # ValueError and deep nesting raises RecursionError.
        return None


def _recover_request_id(line: str) -> types.RequestId | None:
    """The request id of a rejected line, when it carries one the wire accepts.

    JSON-RPC 2.0 §5: an error response carries the id of the request it answers,
    and `null` only when the id could not be determined. A line that *validated*
    badly usually still identifies itself, and answering with `null` would leave
    the client's pending call unmatched - precisely the hang being fixed, since
    a `null` id correlates with nothing in a client's pending map.

    Only the envelope's own top-level `id` counts: an `id` nested inside `params`
    is a tool argument, and attributing the reply to it would resolve an
    unrelated request. A member that is not a valid `RequestId` (a float, a bool,
    an array, an object, or an explicit `null`) is dropped rather than echoed,
    because putting it on the wire would violate the same spec.
    """
    decoded = _lenient_decode(line)
    if not isinstance(decoded, dict):
        return None
    envelope = cast("dict[str, Any]", decoded)
    raw_id: Any = envelope.get("id")
    # `bool` subclasses `int`; JSON `true` is not a request id.
    if isinstance(raw_id, bool):
        return None
    if isinstance(raw_id, str):
        # The lenient decoder tolerates a string id carrying the same lone
        # surrogate that got the line rejected; echoing it would make the reply
        # itself unserializable and take the writer down. Such an id is
        # undeterminable for this server, so it is answered with `null`.
        try:
            raw_id.encode("utf-8")
        except UnicodeEncodeError:
            return None
        return raw_id
    if isinstance(raw_id, int):
        return raw_id
    return None


def _invalid_line_response(line: str) -> types.JSONRPCError:
    """The JSON-RPC error owed to a client whose request line could not be accepted.

    The code follows the rung the line failed at, which is read by replaying only
    the decode stage: `-32700 Parse error` when the JSON layer refuses the line,
    `-32600 Invalid Request` when the JSON is well-formed but not one message.
    (`jsonrpc_message_adapter` is a union of the four message models, so a batch,
    a bare scalar, `{}`, a bad `jsonrpc` version or a missing `method` all fail
    the envelope rung rather than the JSON one.)
    """
    try:
        pydantic_core.from_json(line)
    except ValueError:
        code, message = types.PARSE_ERROR, _PARSE_ERROR_MESSAGE
    else:
        code, message = types.INVALID_REQUEST, _INVALID_REQUEST_MESSAGE
    return types.JSONRPCError(
        jsonrpc="2.0",
        id=_recover_request_id(line),
        error=types.ErrorData(code=code, message=message),
    )


async def _reply_to_invalid_line(write_stream: WriteStream[SessionMessage], line: str, exc: Exception) -> None:
    """Send the error reply for an unusable line instead of leaving the client to time out.

    `JSONRPCDispatcher._dispatch` drops a bare `Exception` item when no
    `on_stream_exception` observer is installed, and a server session installs
    none - so forwarding the exception alone, as this reader used to, produced
    silence on the wire. The exception is still forwarded (observers keep seeing
    it); the reply is what unblocks the caller.
    """
    response = _invalid_line_response(line)
    # Warning, not debug: the line is discarded, and that is worth an operator's
    # attention - the issue reported the silence on stderr as part of the defect.
    logger.warning("rejected stdin line as %s (%s)", response.error.message, type(exc).__name__)
    try:
        await write_stream.send(SessionMessage(response))
    except (anyio.BrokenResourceError, anyio.ClosedResourceError):
        # The session already tore down; a reply that was never written must not
        # take the reader's task group with it.
        logger.debug("dropped %s reply: write stream closed", response.error.code)


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Serve MCP over the process's stdin and stdout.

    While serving, fd 0 points at the null device and fd 1 at stderr, so handlers
    and children read EOF and their stray output misses the wire; both descriptors
    are restored on exit. Explicit streams skip the claim, and a second concurrent
    stdio_server() raises RuntimeError.
    """
    # Re-wrap the binary buffers as UTF-8 text; the std handles' platform encodings are unreliable.
    restore_stdin: Callable[[], None] | None = None
    restore_stdout: Callable[[], None] | None = None
    try:
        if not stdin:
            stdin_buffer, restore_stdin = _claim_fd(0, sys.stdin, "rb", _open_stdin_diversion)
            stdin = anyio.wrap_file(_UnownedTextWrapper(stdin_buffer, encoding="utf-8", errors="replace"))
        if not stdout:
            stdout_buffer, restore_stdout = _claim_fd(1, sys.stdout, "wb", _open_stdout_diversion)
            stdout = anyio.wrap_file(_UnownedTextWrapper(stdout_buffer, encoding="utf-8"))

        read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
        write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

        async def stdin_reader():
            try:
                async with read_stream_writer:
                    async for line in stdin:
                        try:
                            message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                        except Exception as exc:
                            # Forward the fault to observers, and answer the client:
                            # a dropped line leaves its call pending until timeout.
                            await _reply_to_invalid_line(write_stream, line, exc)
                            await read_stream_writer.send(exc)
                            continue

                        session_message = SessionMessage(message)
                        await read_stream_writer.send(session_message)
            except anyio.ClosedResourceError:  # pragma: no cover
                await anyio.lowlevel.checkpoint()

        async def stdout_writer():
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        json = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                        await stdout.write(json + "\n")
                        await stdout.flush()
            except anyio.ClosedResourceError:  # pragma: no cover
                await anyio.lowlevel.checkpoint()

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
    finally:
        if restore_stdout is not None:
            restore_stdout()
        if restore_stdin is not None:
            restore_stdin()
