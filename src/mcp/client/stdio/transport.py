import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO  # Use type directly for type hints if needed, or Any

import anyio
import anyio.lowlevel
from anyio.abc import Process, TaskGroup  # Import TaskGroup directly
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream

import mcp.types as types
from mcp.shared.message import SessionMessage

from .parameters import StdioServerParameters, get_default_environment
from .win32 import (
    create_windows_process,
    get_windows_executable_command,
    terminate_windows_process,
)


# Helper to choose the correct process creation function
async def _create_platform_compatible_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO = sys.stderr,  # For _stderr_reader to use for its output
    cwd: Path | str | None = None,
) -> Process:
    if sys.platform == "win32":
        return await create_windows_process(command, args, env, errlog, cwd)
    else:
        return await anyio.open_process(
            [command, *args],
            env=env,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


# Helper to get platform-specific executable command
def _get_executable_command(command: str) -> str:
    if sys.platform == "win32":
        return get_windows_executable_command(command)
    else:
        return command


class StdioClientTransport:
    def __init__(
        self, server_params: StdioServerParameters, errlog: TextIO = sys.stderr
    ):
        self.server_params = server_params
        self.errlog = errlog
        self.process: Process | None = None
        self._tg: TaskGroup | None = None  # Use imported TaskGroup for type hint

        self.read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]
        self.read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
        self.read_stream_writer, self.read_stream = anyio.create_memory_object_stream(0)

        self.write_stream: MemoryObjectSendStream[SessionMessage]
        self.write_stream_reader: MemoryObjectReceiveStream[SessionMessage]
        self.write_stream, self.write_stream_reader = anyio.create_memory_object_stream(
            0
        )

    async def _stdout_reader(self):
        assert self.process and self.process.stdout, "Process or stdout missing"
        try:
            async with self.read_stream_writer:
                buffer = ""
                async for chunk in TextReceiveStream(
                    self.process.stdout,
                    encoding=self.server_params.encoding,
                    errors=self.server_params.encoding_error_handler,
                ):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        stripped_line = line.strip()
                        if not stripped_line:
                            continue  # Fixed multiple statements on one line
                        try:
                            message = types.JSONRPCMessage.model_validate_json(
                                stripped_line
                            )
                        except Exception as exc:
                            await self.read_stream_writer.send(exc)
                            continue
                        session_message = SessionMessage(message)
                        await self.read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()
        except Exception as e_stdout_task:  # Renamed e to e_stdout_task
            try:
                # Attempt to send the exception to the stream.
                # No reliable is_closed check, rely on send() raising error.
                await self.read_stream_writer.send(e_stdout_task)
            except anyio.ClosedResourceError:
                pass  # Target stream already closed
            except Exception:
                pass

    async def _stdin_writer(self):
        assert self.process and self.process.stdin, "Process or stdin missing"
        try:
            async with self.write_stream_reader:
                async for session_message in self.write_stream_reader:
                    json_data = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    )
                    try:
                        await self.process.stdin.send(
                            (json_data + "\n").encode(
                                encoding=self.server_params.encoding,
                                errors=self.server_params.encoding_error_handler,
                            )
                        )
                    except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                        break
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()
        except Exception:  # Catch general exceptions, e removed as unused
            pass
        finally:
            if self.process and self.process.stdin:
                try:
                    await self.process.stdin.aclose()
                except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                    pass

    async def _stderr_reader(self):
        assert self.process and self.process.stderr, "Process or stderr missing"
        try:
            async for chunk in TextReceiveStream(
                self.process.stderr,
                encoding=self.server_params.encoding,
                errors="replace",
            ):
                if self.errlog and not self.errlog.closed:
                    try:
                        self.errlog.write(chunk)
                        self.errlog.flush()
                    except Exception:
                        pass
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()
        except Exception:
            pass

    async def __aenter__(self):
        command = _get_executable_command(self.server_params.command)
        effective_env = (
            {**get_default_environment(), **self.server_params.env}
            if self.server_params.env is not None
            else get_default_environment()
        )

        # _create_platform_compatible_process is expected to return a Process object
        # or raise an exception if process creation fails.
        self.process = await _create_platform_compatible_process(
            command=command,
            args=self.server_params.args,
            env=effective_env,
            errlog=self.errlog,
            cwd=self.server_params.cwd,
        )

        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()

        self._tg.start_soon(self._stdout_reader)
        self._tg.start_soon(self._stdin_writer)
        self._tg.start_soon(self._stderr_reader)

        return self.read_stream, self.write_stream

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,  # Use built-in type
        exc_val: BaseException | None,
        exc_tb: Any,  # TracebackType can be imported from types
    ) -> None:  # any for TracebackType for simplicity
        try:
            if self._tg:  # self._tg is now correctly typed as TaskGroup | None
                self._tg.cancel_scope.cancel()
                await self._tg.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            self._tg = None
            if self.process:
                try:
                    if sys.platform == "win32":
                        await terminate_windows_process(self.process)
                    else:
                        self.process.terminate()
                        await self.process.wait()
                except ProcessLookupError:
                    pass
                except Exception:
                    pass
                self.process = None

            await self.read_stream.aclose()
            await self.read_stream_writer.aclose()
            await self.write_stream.aclose()
            await self.write_stream_reader.aclose()
