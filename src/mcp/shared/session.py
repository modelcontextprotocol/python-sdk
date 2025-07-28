import logging
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import timedelta
from types import TracebackType
from typing import Any, Generic, Protocol, TypeVar

import anyio
import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic import BaseModel
from typing_extensions import Self

from mcp.shared.exceptions import McpError
from mcp.shared.message import ClientMessageMetadata, MessageMetadata, ServerMessageMetadata, SessionMessage
from mcp.types import (
    CONNECTION_CLOSED,
    INVALID_PARAMS,
    CancelledNotification,
    CancelledNotificationParams,
    ClientNotification,
    ClientRequest,
    ClientResult,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    PingRequest,
    ProgressNotification,
    RequestParams,
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

    async def __call__(self, progress: float, total: float | None, message: str | None) -> None: ...


class RequestResponder(Generic[ReceiveRequestT, SendResultT]):
    """Handles responding to MCP requests and manages request lifecycle.

    This class MUST be used as a context manager to ensure proper cleanup and
    cancellation handling:

    Example:
        with request_responder as resp:
            await resp.respond(result)

    The context manager ensures:
    1. Proper cancellation scope setup and cleanup
    2. Request completion tracking
    3. Cleanup of in-flight requests
    """

    def __init__(
        self,
        request_id: RequestId,
        request_meta: RequestParams.Meta | None,
        request: ReceiveRequestT,
        session: """BaseSession[
            SendRequestT,
            SendNotificationT,
            SendResultT,
            ReceiveRequestT,
            ReceiveNotificationT
        ]""",
        on_complete: Callable[["RequestResponder[ReceiveRequestT, SendResultT]"], Any],
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

    def __enter__(self) -> "RequestResponder[ReceiveRequestT, SendResultT]":
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
            if self._completed:
                self._on_complete(self)
        finally:
            self._entered = False
            if not self._cancel_scope:
                raise RuntimeError("No active cancel scope")
            self._cancel_scope.__exit__(exc_type, exc_val, exc_tb)

    async def respond(self, response: SendResultT | ErrorData) -> None:
        """Send a response for this request.

        Must be called within a context manager block.
        Raises:
            RuntimeError: If not used within a context manager
            AssertionError: If request was already responded to
        """
        if not self._entered:
            raise RuntimeError("RequestResponder must be used as a context manager")
        assert not self._completed, "Request already responded to"

        if not self.cancelled:
            self._completed = True

            await self._session._send_response(  # type: ignore[reportPrivateUsage]
                request_id=self.request_id, response=response
            )

    async def cancel(self) -> None:
        """Cancel this request and mark it as completed."""
        if not self._entered:
            raise RuntimeError("RequestResponder must be used as a context manager")
        if not self._cancel_scope:
            raise RuntimeError("No active cancel scope")

        self._cancel_scope.cancel()
        self._completed = True  # Mark as completed so it's removed from in_flight
        # Send an error response to indicate cancellation
        await self._session._send_response(  # type: ignore[reportPrivateUsage]
            request_id=self.request_id,
            response=ErrorData(code=0, message="Request cancelled", data=None),
        )

    @property
    def in_flight(self) -> bool:
        return not self._completed and not self.cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancel_scope.cancel_called


class RequestStateManager(
    Generic[
        SendRequestT,
        SendResultT,
    ],
):
    def new_request(self, request: SendRequestT) -> RequestId: ...

    def resume(self, request_id: RequestId) -> bool: ...

    async def update_resume_token(self, request_id: RequestId, token: str) -> None: ...

    async def get_resume_token(self, request_id: RequestId) -> str | None: ...

    def add_progress_callback(self, request_id: RequestId, progress_callback: ProgressFnT): ...

    async def send_progress(
        self,
        request_id: RequestId,
        progress: float,
        total: float | None,
        message: str | None,
    ): ...

    async def receive_response(
        self,
        request_id: RequestId,
        timeout: float | None = None,
    ) -> JSONRPCResponse | JSONRPCError | None: ...

    async def handle_response(self, message: JSONRPCResponse | JSONRPCError) -> bool: ...

    async def close_request(self, request_id: RequestId) -> bool: ...

    async def close(self) -> None: ...


class InMemoryRequestStateManager(
    RequestStateManager[
        SendRequestT,
        SendResultT,
    ],
):
    _request_id: int
    _requests: dict[
        RequestId,
        SendRequestT,
    ]
    _response_streams: dict[
        RequestId,
        tuple[
            MemoryObjectSendStream[JSONRPCResponse | JSONRPCError],
            MemoryObjectReceiveStream[JSONRPCResponse | JSONRPCError],
        ],
    ]
    _progress_callbacks: dict[RequestId, list[ProgressFnT]]
    _resume_tokens: dict[RequestId, str]

    def __init__(self):
        self._request_id = 0
        self._requests = {}
        self._response_streams = {}
        self._progress_callbacks = {}
        self._resume_tokens = {}

    def new_request(self, request: SendRequestT) -> RequestId:
        request_id = self._request_id
        self._request_id = request_id + 1

        send_stream, receive_stream = anyio.create_memory_object_stream[JSONRPCResponse | JSONRPCError](1)
        self._response_streams[request_id] = send_stream, receive_stream
        self._requests[request_id] = request

        return request_id

    def resume(self, request_id: RequestId) -> bool:
        if self._requests.get(request_id) is None:
            raise RuntimeError(f"Unknown request {request_id}")

        if request_id in self._response_streams:
            return False
        else:
            send_stream, receive_stream = anyio.create_memory_object_stream[JSONRPCResponse | JSONRPCError](1)
            self._response_streams[request_id] = send_stream, receive_stream
            return True

    async def update_resume_token(self, request_id: RequestId, token: str) -> None:
        self._resume_tokens[request_id] = token

    async def get_resume_token(self, request_id: RequestId) -> str | None:
        return self._resume_tokens.get(request_id)

    def add_progress_callback(self, request_id: RequestId, progress_callback: ProgressFnT):
        progress_list = self._progress_callbacks.get(request_id)
        if progress_list is None:
            progress_list = []
            self._progress_callbacks[request_id] = progress_list

        progress_list.append(progress_callback)

    async def send_progress(
        self,
        request_id: RequestId,
        progress: float,
        total: float | None,
        message: str | None,
    ):
        if request_id in self._progress_callbacks:
            callbacks = self._progress_callbacks[request_id]
            for callback in callbacks:
                await callback(
                    progress,
                    total,
                    message,
                )

    async def receive_response(
        self,
        request_id: RequestId,
        timeout: float | None = None,
    ) -> JSONRPCResponse | JSONRPCError | None:
        _, receive_stream = self._response_streams.get(request_id, [None, None])
        if receive_stream is None:
            raise McpError(
                ErrorData(
                    code=INVALID_PARAMS,
                    message=(f"Unknown request {request_id}"),
                )
            )

        request = self._requests.get(request_id, None)
        assert request is not None

        try:
            with anyio.fail_after(timeout):
                return await receive_stream.receive()
        except anyio.EndOfStream:
            raise McpError(
                ErrorData(
                    code=CONNECTION_CLOSED,
                    message=("Connection closed"),
                )
            )
        except TimeoutError:
            return None

    async def handle_response(self, message: JSONRPCResponse | JSONRPCError) -> bool:
        send_stream, _ = self._response_streams.get(message.id, [None, None])
        if send_stream:
            await send_stream.send(message)
            return True
        else:
            return False

    async def close_request(self, request_id: RequestId) -> bool:
        send_stream, receive_stream = self._response_streams.pop(request_id, [None, None])
        if send_stream is not None:
            await send_stream.aclose()
        if receive_stream is not None:
            await receive_stream.aclose()

        self._requests.pop(request_id, None)
        self._resume_tokens.pop(request_id, None)
        self._progress_callbacks.pop(request_id, None)

        return send_stream is not None

    async def close(self):
        for id, [send_stream, receive_stream] in self._response_streams.copy().items():
            await receive_stream.aclose()
            try:
                error = ErrorData(code=CONNECTION_CLOSED, message="Connection closed")
                await send_stream.send(JSONRPCError(jsonrpc="2.0", id=id, error=error))
            except anyio.BrokenResourceError:
                # Stream already be closed
                pass
            except anyio.ClosedResourceError:
                # Stream already be closed
                pass
            finally:
                await send_stream.aclose()
                self._response_streams.pop(id)


class BaseSession(
    Generic[
        SendRequestT,
        SendNotificationT,
        SendResultT,
        ReceiveRequestT,
        ReceiveNotificationT,
    ],
):
    """
    Implements an MCP "session" on top of read/write streams, including features
    like request/response linking, notifications, and progress.

    This class is an async context manager that automatically starts processing
    messages when entered.
    """

    _in_flight: dict[RequestId, RequestResponder[ReceiveRequestT, SendResultT]]

    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        receive_request_type: type[ReceiveRequestT],
        receive_notification_type: type[ReceiveNotificationT],
        # If none, reading will never time out
        read_timeout_seconds: timedelta | None = None,
        request_state_manager: RequestStateManager[SendRequestT, SendResultT] | None = None,
    ) -> None:
        self._read_stream = read_stream
        self._write_stream = write_stream
        self._receive_request_type = receive_request_type
        self._receive_notification_type = receive_notification_type
        self._session_read_timeout_seconds = read_timeout_seconds
        self._exit_stack = AsyncExitStack()
        self._in_flight = {}
        self._request_state_manager = request_state_manager or InMemoryRequestStateManager()

    async def __aenter__(self) -> Self:
        self._task_group = anyio.create_task_group()
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._receive_loop)
        return self

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

    async def start_request(
        self,
        request: SendRequestT,
        metadata: MessageMetadata = None,
        progress_callback: ProgressFnT | None = None,
    ) -> RequestId:
        """
        Starts a request.

        Do not use this method to emit notifications! Use send_notification()
        instead.
        """
        request_id = self._request_state_manager.new_request(request)
        # Set up progress token if progress callback is provided
        request_data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        if progress_callback is not None:
            # Use request_id as progress token
            if "params" not in request_data:
                request_data["params"] = {}
            if "_meta" not in request_data["params"]:
                request_data["params"]["_meta"] = {}
            request_data["params"]["_meta"]["progressToken"] = request_id
            # Store the callback for this request
            self._request_state_manager.add_progress_callback(request_id, progress_callback)

        jsonrpc_request = JSONRPCRequest(
            jsonrpc="2.0",
            id=request_id,
            **request_data,
        )

        try:
            await self._write_stream.send(SessionMessage(message=JSONRPCMessage(jsonrpc_request), metadata=metadata))
            return request_id
        except Exception as e:
            await self._request_state_manager.close_request(request_id)
            raise e

    async def join_request(
        self,
        request_id: RequestId,
        result_type: type[ReceiveResultT],
        request_read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
        done_on_timeout: bool = True,
    ) -> ReceiveResultT | None:
        """
        Joins a request previously started via start_request.
        
        Returns the result or None if timeout is reached.
        """
        resume = self._request_state_manager.resume(request_id)

        if progress_callback is not None:
            self._request_state_manager.add_progress_callback(request_id, progress_callback)

        # request read timeout takes precedence over session read timeout
        timeout = None
        if request_read_timeout_seconds is not None:
            timeout = request_read_timeout_seconds.total_seconds()
        elif self._session_read_timeout_seconds is not None:
            timeout = self._session_read_timeout_seconds.total_seconds()

        if resume:
            resume_token = await self._request_state_manager.get_resume_token(request_id)
            if resume_token is not None:
                metadata = ClientMessageMetadata(resumption_token=resume_token)

                request_data = PingRequest(method="ping").model_dump(by_alias=True, mode="json", exclude_none=True)

                jsonrpc_request = JSONRPCRequest(
                    jsonrpc="2.0",
                    id=request_id,
                    **request_data,
                )

                await self._write_stream.send(
                    SessionMessage(message=JSONRPCMessage(jsonrpc_request), metadata=metadata)
                )

        response_or_error = await self._request_state_manager.receive_response(request_id, timeout)

        if response_or_error is None:
            if done_on_timeout:
                await self._request_state_manager.close_request(request_id)  
            return None
        elif isinstance(response_or_error, JSONRPCError):
            if response_or_error.error.code == httpx.codes.REQUEST_TIMEOUT.value:
                if done_on_timeout:
                    await self._request_state_manager.close_request(request_id)
                return None
            else:
                await self._request_state_manager.close_request(request_id)
                raise McpError(response_or_error.error)
        else :
            await self._request_state_manager.close_request(request_id)
            return result_type.model_validate(response_or_error.result)


    async def cancel_request(self, request_id: RequestId) -> bool:
        """
        Cancels a request previously started via start_request
        """
        closed = await self._request_state_manager.close_request(request_id)

        if closed:
            notification = CancelledNotification(
                method="notifications/cancelled",
                params=CancelledNotificationParams(requestId=request_id, reason="cancelled"),
            )
            await self.send_notification(notification, request_id)  # type: ignore
            return True
        else:
            return False

    async def send_request(
        self,
        request: SendRequestT,
        result_type: type[ReceiveResultT],
        request_read_timeout_seconds: timedelta | None = None,
        metadata: MessageMetadata = None,
        progress_callback: ProgressFnT | None = None,
    ) -> ReceiveResultT:
        """
        Sends a request and wait for a response. Raises an McpError if the
        response contains an error. If a request read timeout is provided, it
        will take precedence over the session read timeout.

        Do not use this method to emit notifications! Use send_notification()
        instead.
        """
        request_id = await self.start_request(request, metadata, progress_callback)
        try:
            result = await self.join_request(request_id, result_type, request_read_timeout_seconds)
            if result is None:
                raise McpError(
                    ErrorData(
                        code=httpx.codes.REQUEST_TIMEOUT,
                        message=(
                            f"Timed out while waiting for response to "
                            f"{request.__class__.__name__}. Waited "
                            f"{request_read_timeout_seconds} seconds."
                        ),
                    )
                )
            else:
                return result
        finally:
            await self._request_state_manager.close_request(request_id)

    async def send_notification(
        self,
        notification: SendNotificationT,
        related_request_id: RequestId | None = None,
    ) -> None:
        """
        Emits a notification, which is a one-way message that does not expect
        a response.
        """
        # Some transport implementations may need to set the related_request_id
        # to attribute to the notifications to the request that triggered them.
        jsonrpc_notification = JSONRPCNotification(
            jsonrpc="2.0",
            **notification.model_dump(by_alias=True, mode="json", exclude_none=True),
        )
        session_message = SessionMessage(
            message=JSONRPCMessage(jsonrpc_notification),
            metadata=ServerMessageMetadata(related_request_id=related_request_id) if related_request_id else None,
        )
        await self._write_stream.send(session_message)

    async def _send_response(self, request_id: RequestId, response: SendResultT | ErrorData) -> None:
        if isinstance(response, ErrorData):
            jsonrpc_error = JSONRPCError(jsonrpc="2.0", id=request_id, error=response)
            session_message = SessionMessage(message=JSONRPCMessage(jsonrpc_error))
            await self._write_stream.send(session_message)
        else:
            jsonrpc_response = JSONRPCResponse(
                jsonrpc="2.0",
                id=request_id,
                result=response.model_dump(by_alias=True, mode="json", exclude_none=True),
            )
            session_message = SessionMessage(message=JSONRPCMessage(jsonrpc_response))
            await self._write_stream.send(session_message)

    async def _receive_loop(self) -> None:
        async with (
            self._read_stream,
            self._write_stream,
        ):
            try:
                async for message in self._read_stream:
                    if isinstance(message, Exception):
                        await self._handle_incoming(message)
                    elif isinstance(message.message.root, JSONRPCRequest):
                        try:
                            validated_request = self._receive_request_type.model_validate(
                                message.message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                            )
                            responder = RequestResponder(
                                request_id=message.message.root.id,
                                request_meta=validated_request.root.params.meta
                                if validated_request.root.params
                                else None,
                                request=validated_request,
                                session=self,
                                on_complete=lambda r: self._in_flight.pop(r.request_id, None),
                                message_metadata=message.metadata,
                            )
                            self._in_flight[responder.request_id] = responder
                            await self._received_request(responder)

                            if not responder._completed:  # type: ignore[reportPrivateUsage]
                                await self._handle_incoming(responder)
                        except Exception as e:
                            # For request validation errors, send a proper JSON-RPC error
                            # response instead of crashing the server
                            logging.warning(f"Failed to validate request: {e}")
                            logging.debug(f"Message that failed validation: {message.message.root}")
                            error_response = JSONRPCError(
                                jsonrpc="2.0",
                                id=message.message.root.id,
                                error=ErrorData(
                                    code=INVALID_PARAMS,
                                    message="Invalid request parameters",
                                    data="",
                                ),
                            )
                            session_message = SessionMessage(message=JSONRPCMessage(error_response))
                            await self._write_stream.send(session_message)

                    elif isinstance(message.message.root, JSONRPCNotification):
                        try:
                            notification = self._receive_notification_type.model_validate(
                                message.message.root.model_dump(by_alias=True, mode="json", exclude_none=True)
                            )
                            # Handle cancellation notifications
                            if isinstance(notification.root, CancelledNotification):
                                cancelled_id = notification.root.params.requestId
                                if cancelled_id in self._in_flight:
                                    await self._in_flight[cancelled_id].cancel()
                            else:
                                # Handle progress notifications callback
                                if isinstance(notification.root, ProgressNotification):
                                    progress_token = notification.root.params.progressToken
                                    # If there is a progress callback for this token,
                                    # call it with the progress information
                                    await self._request_state_manager.send_progress(
                                        progress_token,
                                        notification.root.params.progress,
                                        notification.root.params.total,
                                        notification.root.params.message,
                                    )
                                await self._received_notification(notification)
                                await self._handle_incoming(notification)
                        except Exception as e:
                            # For other validation errors, log and continue
                            logging.warning(
                                f"Failed to validate notification: {e}. Message was: {message.message.root}"
                            )
                    else:  # Response or error
                        handled = await self._request_state_manager.handle_response(message.message.root)
                        if not handled:
                            await self._handle_incoming(
                                RuntimeError(f"Received response with an unknown request ID: {message}")
                            )

            except anyio.ClosedResourceError:
                # This is expected when the client disconnects abruptly.
                # Without this handler, the exception would propagate up and
                # crash the server's task group.
                logging.debug("Read stream closed by client")
            except Exception as e:
                # Other exceptions are not expected and should be logged. We purposefully
                # catch all exceptions here to avoid crashing the server.
                logging.exception(f"Unhandled exception in receive loop: {e}")
            finally:
                # after the read stream is closed, we need to send errors
                # to any pending requests
                await self._request_state_manager.close()

    async def _received_request(self, responder: RequestResponder[ReceiveRequestT, SendResultT]) -> None:
        """
        Can be overridden by subclasses to handle a request without needing to
        listen on the message stream.

        If the request is responded to within this method, it will not be
        forwarded on to the message stream.
        """

    async def _received_notification(self, notification: ReceiveNotificationT) -> None:
        """
        Can be overridden by subclasses to handle a notification without needing
        to listen on the message stream.
        """

    async def send_progress_notification(
        self,
        progress_token: str | int,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        """
        Sends a progress notification for a request that is currently being
        processed.
        """

    async def _handle_incoming(
        self,
        req: RequestResponder[ReceiveRequestT, SendResultT] | ReceiveNotificationT | Exception,
    ) -> None:
        """A generic handler for incoming messages. Overwritten by subclasses."""
        pass
