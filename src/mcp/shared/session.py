from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Generic, Protocol, TypeVar

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import BaseModel, TypeAdapter
from typing_extensions import Self

from mcp.shared.dispatcher import Dispatcher, JSONRPCDispatcher
from mcp.shared.exceptions import MCPError
from mcp.shared.message import MessageMetadata, SessionMessage
from mcp.shared.response_router import ResponseRouter
from mcp.types import (
    INVALID_PARAMS,
    REQUEST_TIMEOUT,
    CancelledNotification,
    ClientNotification,
    ClientRequest,
    ClientResult,
    ErrorData,
    ProgressNotification,
    ProgressToken,
    RequestParamsMeta,
    ServerNotification,
    ServerRequest,
    ServerResult,
)

SendRequestT = TypeVar("SendRequestT", ClientRequest, ServerRequest)
SendResultT = TypeVar("SendResultT", ClientResult, ServerResult)
SendNotificationT = TypeVar("SendNotificationT", ClientNotification, ServerNotification)
ReceiveRequestT = TypeVar("ReceiveRequestT", ClientRequest, ServerRequest)
ReceiveResultT = TypeVar("ReceiveResultT", bound=BaseModel)
ReceiveNotificationT = TypeVar("ReceiveNotificationT", ClientNotification, ServerNotification)

RequestId = str | int


class ProgressFnT(Protocol):
    """Protocol for progress notification callbacks."""

    async def __call__(
        self, progress: float, total: float | None, message: str | None
    ) -> None: ...  # pragma: no branch


class RequestResponder(Generic[ReceiveRequestT, SendResultT]):
    """Handles responding to MCP requests and manages request lifecycle.

    This class MUST be used as a context manager to ensure proper cleanup and
    cancellation handling:

    Example:
        ```python
        with request_responder as resp:
            await resp.respond(result)
        ```

    The context manager ensures:
    1. Proper cancellation scope setup and cleanup
    2. Request completion tracking
    3. Cleanup of in-flight requests
    """

    def __init__(
        self,
        request_id: RequestId,
        request_meta: RequestParamsMeta | None,
        request: ReceiveRequestT,
        session: BaseSession[SendRequestT, SendNotificationT, SendResultT, ReceiveRequestT, ReceiveNotificationT],
        on_complete: Callable[[RequestResponder[ReceiveRequestT, SendResultT]], Any],
        message_metadata: MessageMetadata = None,
    ) -> None:
        self.request_id = request_id
        self.request_meta = request_meta
        self.request = request
        self.message_metadata = message_metadata
        self._session = session
        self._completed = False
        self._cancel_scope = anyio.CancelScope()
        self._on_complete = on_complete
        self._entered = False  # Track if we're in a context manager

    def __enter__(self) -> RequestResponder[ReceiveRequestT, SendResultT]:
        """Enter the context manager, enabling request cancellation tracking."""
        self._entered = True
        self._cancel_scope = anyio.CancelScope()
        self._cancel_scope.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager, performing cleanup and notifying completion."""
        try:
            if self._completed:  # pragma: no branch
                self._on_complete(self)
        finally:
            self._entered = False
            if not self._cancel_scope:  # pragma: no cover
                raise RuntimeError("No active cancel scope")
            self._cancel_scope.__exit__(exc_type, exc_val, exc_tb)

    async def respond(self, response: SendResultT | ErrorData) -> None:
        """Send a response for this request.

        Must be called within a context manager block.

        Raises:
            RuntimeError: If not used within a context manager
            AssertionError: If request was already responded to
        """
        if not self._entered:  # pragma: no cover
            raise RuntimeError("RequestResponder must be used as a context manager")
        assert not self._completed, "Request already responded to"

        if not self.cancelled:  # pragma: no branch
            self._completed = True

            await self._session._send_response(  # type: ignore[reportPrivateUsage]
                request_id=self.request_id, response=response
            )

    async def cancel(self) -> None:
        """Cancel this request and mark it as completed."""
        if not self._entered:  # pragma: no cover
            raise RuntimeError("RequestResponder must be used as a context manager")
        if not self._cancel_scope:  # pragma: no cover
            raise RuntimeError("No active cancel scope")

        self._cancel_scope.cancel()
        self._completed = True  # Mark as completed so it's removed from in_flight
        # Send an error response to indicate cancellation
        await self._session._send_response(  # type: ignore[reportPrivateUsage]
            request_id=self.request_id,
            response=ErrorData(code=0, message="Request cancelled"),
        )

    @property
    def in_flight(self) -> bool:  # pragma: no cover
        return not self._completed and not self.cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancel_scope.cancel_called


class BaseSession(
    Generic[
        SendRequestT,
        SendNotificationT,
        SendResultT,
        ReceiveRequestT,
        ReceiveNotificationT,
    ],
):
    """Implements an MCP "session" on top of a wire-protocol dispatcher, including
    features like request/response linking, notifications, and progress.

    This class is an async context manager that automatically starts processing
    messages when entered.

    By default the session constructs a ``JSONRPCDispatcher`` from the supplied
    read/write streams — this is the path every built-in transport uses. A custom
    dispatcher can be passed via the ``dispatcher`` keyword argument to use a
    different wire protocol; see ``mcp.shared.dispatcher``.
    """

    _request_id: int
    _in_flight: dict[RequestId, RequestResponder[ReceiveRequestT, SendResultT]]
    _progress_callbacks: dict[RequestId, ProgressFnT]
    _response_routers: list[ResponseRouter]

    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception] | None = None,
        write_stream: MemoryObjectSendStream[SessionMessage] | None = None,
        # If none, reading will never time out
        read_timeout_seconds: float | None = None,
        *,
        dispatcher: Dispatcher | None = None,
    ) -> None:
        self._request_id = 0
        self._session_read_timeout_seconds = read_timeout_seconds
        self._in_flight = {}
        self._progress_callbacks = {}
        self._response_routers = []
        self._exit_stack = AsyncExitStack()

        if dispatcher is None:
            if read_stream is None or write_stream is None:
                raise TypeError("either dispatcher or both read_stream and write_stream must be provided")
            dispatcher = JSONRPCDispatcher(read_stream, write_stream, self._response_routers)
        self._dispatcher = dispatcher

    def add_response_router(self, router: ResponseRouter) -> None:
        """Register a response router to handle responses for non-standard requests.

        Response routers are checked in order before falling back to the default
        response stream mechanism. This is used by TaskResultHandler to route
        responses for queued task requests back to their resolvers.

        !!! warning
            This is an experimental API that may change without notice.

        Args:
            router: A ResponseRouter implementation
        """
        self._response_routers.append(router)

    async def __aenter__(self) -> Self:
        self._dispatcher.set_handlers(
            on_request=self._on_incoming_request,
            on_notification=self._on_incoming_notification,
            on_error=self._handle_incoming,
        )
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._run)
        return self

    async def _run(self) -> None:
        """Run the dispatcher's receive loop. Hook for subclasses that need to
        wrap the loop's lifetime (e.g. to close resources when it exits)."""
        await self._dispatcher.run()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self._exit_stack.aclose()
        # Using BaseSession as a context manager should not block on exit (this
        # would be very surprising behavior), so make sure to cancel the tasks
        # in the task group.
        self._task_group.cancel_scope.cancel()
        return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

    async def send_request(
        self,
        request: SendRequestT,
        result_type: type[ReceiveResultT],
        request_read_timeout_seconds: float | None = None,
        metadata: MessageMetadata = None,
        progress_callback: ProgressFnT | None = None,
    ) -> ReceiveResultT:
        """Sends a request and waits for a response.

        Raises an MCPError if the response contains an error. If a request read timeout is provided, it will take
        precedence over the session read timeout.

        Do not use this method to emit notifications! Use send_notification() instead.
        """
        request_id = self._request_id
        self._request_id = request_id + 1

        # Set up progress token if progress callback is provided
        request_data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        if progress_callback is not None:
            # Use request_id as progress token
            if "params" not in request_data:  # pragma: lax no cover
                request_data["params"] = {}
            if "_meta" not in request_data["params"]:  # pragma: lax no cover
                request_data["params"]["_meta"] = {}
            request_data["params"]["_meta"]["progressToken"] = request_id
            # Store the callback for this request
            self._progress_callbacks[request_id] = progress_callback

        # request read timeout takes precedence over session read timeout
        timeout = request_read_timeout_seconds or self._session_read_timeout_seconds

        try:
            try:
                result = await self._dispatcher.send_request(request_id, request_data, metadata, timeout)
            except TimeoutError:
                class_name = request.__class__.__name__
                message = f"Timed out while waiting for response to {class_name}. Waited {timeout} seconds."
                raise MCPError(code=REQUEST_TIMEOUT, message=message)
            return result_type.model_validate(result, by_name=False)
        finally:
            self._progress_callbacks.pop(request_id, None)

    async def send_notification(
        self,
        notification: SendNotificationT,
        related_request_id: RequestId | None = None,
    ) -> None:
        """Emits a notification, which is a one-way message that does not expect a response."""
        # Some transport implementations may need to set the related_request_id
        # to attribute to the notifications to the request that triggered them.
        await self._dispatcher.send_notification(
            notification.model_dump(by_alias=True, mode="json", exclude_none=True),
            related_request_id,
        )

    async def _send_response(self, request_id: RequestId, response: SendResultT | ErrorData) -> None:
        if isinstance(response, ErrorData):
            await self._dispatcher.send_response(request_id, response)
        else:
            await self._dispatcher.send_response(
                request_id,
                response.model_dump(by_alias=True, mode="json", exclude_none=True),
            )

    @property
    def _receive_request_adapter(self) -> TypeAdapter[ReceiveRequestT]:
        """Each subclass must provide its own request adapter."""
        raise NotImplementedError

    @property
    def _receive_notification_adapter(self) -> TypeAdapter[ReceiveNotificationT]:
        raise NotImplementedError

    async def _on_incoming_request(
        self, request_id: RequestId, payload: dict[str, Any], metadata: MessageMetadata
    ) -> None:
        """Dispatcher callback: a request arrived from the peer."""
        try:
            validated_request = self._receive_request_adapter.validate_python(payload, by_name=False)
            responder = RequestResponder(
                request_id=request_id,
                request_meta=validated_request.params.meta if validated_request.params else None,
                request=validated_request,
                session=self,
                on_complete=lambda r: self._in_flight.pop(r.request_id, None),
                message_metadata=metadata,
            )
            self._in_flight[responder.request_id] = responder
            await self._received_request(responder)

            if not responder._completed:  # type: ignore[reportPrivateUsage]
                await self._handle_incoming(responder)
        except Exception:
            logging.warning("Failed to validate request", exc_info=True)
            logging.debug(f"Message that failed validation: {payload}")
            await self._dispatcher.send_response(
                request_id,
                ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data=""),
            )

    async def _on_incoming_notification(self, payload: dict[str, Any]) -> None:
        """Dispatcher callback: a notification arrived from the peer."""
        try:
            notification = self._receive_notification_adapter.validate_python(payload, by_name=False)
            # Handle cancellation notifications
            if isinstance(notification, CancelledNotification):
                cancelled_id = notification.params.request_id
                if cancelled_id in self._in_flight:  # pragma: no branch
                    await self._in_flight[cancelled_id].cancel()
            else:
                # Handle progress notifications callback
                if isinstance(notification, ProgressNotification):
                    progress_token = notification.params.progress_token
                    # If there is a progress callback for this token,
                    # call it with the progress information
                    if progress_token in self._progress_callbacks:
                        callback = self._progress_callbacks[progress_token]
                        try:
                            await callback(
                                notification.params.progress,
                                notification.params.total,
                                notification.params.message,
                            )
                        except Exception:
                            logging.exception("Progress callback raised an exception")
                await self._received_notification(notification)
                await self._handle_incoming(notification)
        except Exception:
            logging.warning(  # pragma: no cover
                f"Failed to validate notification. Message was: {payload}",
                exc_info=True,
            )

    async def _received_request(self, responder: RequestResponder[ReceiveRequestT, SendResultT]) -> None:
        """Can be overridden by subclasses to handle a request without needing to
        listen on the message stream.

        If the request is responded to within this method, it will not be
        forwarded on to the message stream.
        """

    async def _received_notification(self, notification: ReceiveNotificationT) -> None:
        """Can be overridden by subclasses to handle a notification without needing
        to listen on the message stream.
        """

    async def send_progress_notification(
        self,
        progress_token: ProgressToken,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """Sends a progress notification for a request that is currently being processed."""

    async def _handle_incoming(
        self, req: RequestResponder[ReceiveRequestT, SendResultT] | ReceiveNotificationT | Exception
    ) -> None:
        """A generic handler for incoming messages. Overridden by subclasses."""
