class ResultThingy:
    result: Any  # final result - always set (last item from stream, or single result)
    _is_stream: bool
    _stream: MemoryObjectReceiveStream  # for streaming results
    _handler: Callable  # stored handler to run
    _task_group: anyio.abc.TaskGroup
    _cancel_scope: anyio.CancelScope

    async def __aenter__(self) -> "ResultThingy":
        # start the task and wait for it to signal ready
        self._is_stream = await self._task_group.start(self._handler)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self._cancel_scope.cancel()
        # cleanup streams, etc.

    def is_stream(self) -> bool:
        return self._is_stream

    async def content_stream(self) -> AsyncGenerator[Any, None]:
        async for item in self._stream:
            self.result = item  # last one becomes final result
            yield item


class JsonHandler:
    def __init__(self, task_group: anyio.abc.TaskGroup):
        self._task_group = task_group

    def handle_message(self, json_blob, session_metadata) -> ResultThingy:
        send_stream, receive_stream = anyio.create_memory_object_stream()

        result_thingy = ResultThingy(...)  # forward ref for closure

        async def handle_runner(*, task_status: anyio.abc.TaskStatus):
            # do the work, determine if streaming...
            if will_stream:
                task_status.started(True)
                for chunk in intermediate_chunks:
                    await send_stream.send(chunk)
                await send_stream.send(final_result)  # last item = final result
                await send_stream.aclose()
            else:
                result_thingy.result = final_result
                task_status.started(False)

        return ResultThingy(
            _handler=handle_runner,
            _stream=receive_stream,
            _task_group=self._task_group,
        )


class HTTPHandler:
    def __init__(self, json_handler: JsonHandler):
        self.json_handler = json_handler

    async def handle_post(self, post_req, send):
        try:
            json_blob, metadata = deserialize(post_req)
        except ValueError:
            return error

        result = self.json_handler.handle_message(json_blob, metadata)
        async with result:
            if result.is_stream():
                content_stream = [*([priming_event] if supported else []), result.content_stream()]
                await EventSourceResponse(content_stream, send)()
            else:
                await Response(result.result)





