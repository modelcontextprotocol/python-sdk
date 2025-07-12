import asyncio
import logging
from collections.abc import Coroutine
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, TypeVar

from pydantic import AnyUrl, BaseModel, ConfigDict, Field

import mcp
from mcp import types
from mcp.client.exceptions import ConnectTimeOut
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError
from mcp.shared.session import ProgressFnT
from mcp.types import StreamalbeHttpClientParams

logger = logging.getLogger(__name__)

R = TypeVar("R")


class ClientSessionState(BaseModel):
    session: mcp.ClientSession | None = None
    lifespan_task: asyncio.Task[Any] | None = None
    running_event: asyncio.Event = Field(default_factory=asyncio.Event)
    error: Exception | None = None
    request_task: dict[str, asyncio.Task[Any]] = Field(default_factory=dict)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def lifespan(self) -> asyncio.Task[Any]:
        if self.lifespan_task is None:
            raise RuntimeError("lifespan_task is not set")
        return self.lifespan_task

    @property
    def active_session(self) -> mcp.ClientSession:
        if self.session is None:
            raise RuntimeError("session is not set")
        return self.session


class ClientConnectionManager:
    def __init__(
        self,
    ):
        self._session: dict[str, ClientSessionState] = {}

    async def connect(self, parameter: StreamalbeHttpClientParams):
        logger.info(f"Attempting to connect to MCP server: {parameter.name} ({parameter.url})")
        state = ClientSessionState()
        if not self._is_session_exists(parameter.name):
            self._session[parameter.name] = state
            logger.debug(f"Session state created for: {parameter.name}")
        else:
            raise McpError(
                types.ErrorData(
                    code=types.CONNECTION_CLOSED,
                    message=f"Session with name '{parameter.name}' already exists. \
                            Duplicate connections are not allowed.",
                )
            )
        ready_future = asyncio.get_running_loop().create_future()

        task = asyncio.create_task(self._maintain_session(parameter, ready_future))
        state.lifespan_task = task

        try:
            await asyncio.wait_for(ready_future, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task  # 等待 task 真正結束或取消
            except asyncio.CancelledError:
                pass
            state.error = ConnectTimeOut(f"Connection to {parameter.name} timed out")
            raise state.error
        except Exception as e:
            task.cancel()
            state.error = e
            raise e

    async def _maintain_session(self, parameter: StreamalbeHttpClientParams, connect_res: asyncio.Future[Any]):
        try:
            async with self._session_context(parameter):
                if not connect_res.done():
                    connect_res.set_result(True)

                logger.debug(f"Session maintenance started for: {parameter.name}. Waiting for shutdown event...")
                await self._session[parameter.name].running_event.wait()
                logger.info(f"Graceful shutdown initiated for session: {parameter.name}")

        except Exception as e:
            if not connect_res.done():
                connect_res.set_exception(e)
            self._session[parameter.name].running_event.set()
            self._session[parameter.name].error = e
            raise e

    @asynccontextmanager
    async def _session_context(self, parameter: StreamalbeHttpClientParams):
        try:
            async with streamablehttp_client(parameter.url) as streams:
                read_stream, write_stream, _ = streams
                async with mcp.ClientSession(read_stream, write_stream) as session:
                    state = self._session[parameter.name]
                    state.session = session

                    logger.info(f"Connected to MCP server: {parameter.name} ({parameter.url})")
                    yield
                    logger.info(f"MCP server {parameter.name} ({parameter.url}): disconnected")

        except Exception as e:
            raise e

    def _is_session_exists(self, session_name: str) -> bool:
        if session_name in self._session:
            return True
        return False

    def _validate_session(self, session_name: str) -> ClientSessionState:
        if self._is_session_exists(session_name):
            state = self._session[session_name]
            if state.error:
                raise McpError(
                    types.ErrorData(
                        code=types.CONNECTION_CLOSED,
                        message=f"Session with name '{session_name}' has error. {state.error}",
                    )
                )
            return state
        else:
            raise McpError(
                types.ErrorData(
                    code=types.CONNECTION_CLOSED,
                    message=f"Session with name '{session_name}' does not exist. Please establish a connection first.",
                )
            )

    async def _safe_run_task(self, session_name: str, task_cor: Coroutine[Any, Any, R]) -> R:
        actived_task = asyncio.create_task(task_cor)

        async def monitor():
            await asyncio.sleep(0.1)
            while not actived_task.done():
                if self._session[session_name].error is not None:
                    actived_task.cancel()
                    break

                await asyncio.sleep(2)

        asyncio.create_task(monitor())
        try:
            res = await actived_task
        except asyncio.exceptions.CancelledError as err:
            session_err = self._session[session_name].error
            if session_err is not None:
                raise session_err
            raise err
        # except Exception as err:
        #     raise err
        return res

    async def session_initialize(self, session_name: str) -> types.InitializeResult:
        session_state = self._validate_session(session_name)

        try:
            res = await self._safe_run_task(session_name, session_state.active_session.initialize())

        except Exception as e:
            raise e

        return res

    async def session_send_pings(self, session_name: str) -> types.EmptyResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(session_name, session_state.active_session.send_ping())

    async def session_send_progress_notification(
        self,
        session_name: str,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.send_progress_notification(progress_token, progress, total, message),
        )

    async def session_set_logging_level(self, session_name: str, level: types.LoggingLevel) -> types.EmptyResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(session_name, session_state.active_session.set_logging_level(level))

    async def session_list_resources(self, session_name: str, cursor: str | None = None) -> types.ListResourcesResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.list_resources(cursor),
        )

    async def session_list_resource_templates(
        self, session_name: str, cursor: str | None = None
    ) -> types.ListResourceTemplatesResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.list_resource_templates(cursor),
        )

    async def session_read_resource(self, session_name: str, uri: AnyUrl) -> types.ReadResourceResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.read_resource(uri),
        )

    async def session_subscribe_resource(self, session_name: str, uri: AnyUrl) -> types.EmptyResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.subscribe_resource(uri),
        )

    async def session_unsubscribe_resource(self, session_name: str, uri: AnyUrl) -> types.EmptyResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.unsubscribe_resource(uri),
        )

    async def session_call_tool(
        self,
        session_name: str,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
    ) -> types.CallToolResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.call_tool(name, arguments, read_timeout_seconds, progress_callback),
        )

    async def session_list_prompts(self, session_name: str, cursor: str | None = None) -> types.ListPromptsResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.list_prompts(cursor),
        )

    async def session_get_prompt(
        self, session_name: str, name: str, arguments: dict[str, str] | None = None
    ) -> types.GetPromptResult:
        session_state = self._validate_session(session_name)
        return await self._safe_run_task(
            session_name,
            session_state.active_session.get_prompt(name, arguments),
        )

    async def session_list_tools(self, session_name: str, cursor: str | None = None) -> types.ListToolsResult:
        session_state = self._validate_session(session_name)

        return await self._safe_run_task(session_name, session_state.active_session.list_tools(cursor))

    async def session_send_roots_list_changed(self, session_name: str) -> None:
        session_state = self._validate_session(session_name)

        return await self._safe_run_task(session_name, session_state.active_session.send_roots_list_changed())

    async def disconnect(self, name: str) -> None:
        session = self._session[name]
        if not session.session:
            return

        if session.lifespan_task and not session.lifespan_task.done():
            session.running_event.set()

        try:
            await session.lifespan
        except Exception as e:
            raise McpError(
                types.ErrorData(
                    code=types.CONNECTION_CLOSED,
                    message=f"MCP server {name} disconnect failed {e}",
                )
            )
        finally:
            session.session = None
            session.lifespan_task = None
