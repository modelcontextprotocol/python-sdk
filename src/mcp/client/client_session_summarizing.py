from datetime import timedelta
from typing import Any

import tiktoken
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from mcp.client.session import ClientSession
from mcp.shared.context import RequestContext
from mcp.shared.message import SessionMessage
from mcp.types import CreateMessageRequestParams, CreateMessageResult, SamplingMessage, TextContent

DEFAULT_MAX_TOKENS = 4000
DEFAULT_SUMMARIZE_THRESHOLD = 0.8
DEFAULT_SUMMARY_PROMPT = "Summarize the following conversation succinctly, preserving key facts:\n\n"


class ClientSessionSummarizing(ClientSession):
    def __init__(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        read_timeout_seconds: timedelta | None = None,
        sampling_callback: Any | None = None,
        elicitation_callback: Any | None = None,
        list_roots_callback: Any | None = None,
        logging_callback: Any | None = None,
        message_handler: Any | None = None,
        client_info: Any | None = None,
        max_tokens: int | None = None,
        summarize_threshold: float | None = None,
        summary_prompt: str | None = None,
    ) -> None:
        super().__init__(
            read_stream=read_stream,
            write_stream=write_stream,
            read_timeout_seconds=read_timeout_seconds,
            sampling_callback=sampling_callback,
            elicitation_callback=elicitation_callback,
            list_roots_callback=list_roots_callback,
            logging_callback=logging_callback,
            message_handler=message_handler,
            client_info=client_info,
        )
        self.history: list[SamplingMessage] = []
        self.max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        self.summarize_threshold = summarize_threshold or DEFAULT_SUMMARIZE_THRESHOLD
        self.summary_prompt = summary_prompt or DEFAULT_SUMMARY_PROMPT
        # Override the sampling callback to include our summarization logic
        self._sampling_callback = self._summarizing_sampling_callback

    async def _summarizing_sampling_callback(
        self,
        context: RequestContext["ClientSession", Any],
        params: CreateMessageRequestParams,
    ) -> CreateMessageResult:
        """Custom sampling callback that includes summarization logic."""
        # Add messages to history
        self.history.extend(params.messages)

        # Check if we need to summarize
        if self.token_count() > self.max_tokens * self.summarize_threshold:
            await self.summarize_context()

        # For now, return a simple response
        # In a real implementation, you might want to call an LLM service here
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="Message processed with summarization"),
            model="summarizing-model",
            stopReason="endTurn",
        )

    def token_count(self) -> int:
        """Calculate token count for all messages in history."""
        tokenizer = tiktoken.get_encoding("cl100k_base")
        total_tokens = 0

        for message in self.history:
            if isinstance(message.content, TextContent):
                total_tokens += len(tokenizer.encode(message.content.text))
            elif isinstance(message.content, str):
                total_tokens += len(tokenizer.encode(message.content))

        return total_tokens

    async def summarize_context(self) -> None:
        """Summarize the conversation history and replace it with a summary."""
        if not self.history:
            return

        # Create a summary prompt from all messages
        summary_text = self.summary_prompt
        for message in self.history:
            if isinstance(message.content, TextContent):
                summary_text += f"{message.role}: {message.content.text}\n"
            elif isinstance(message.content, str):
                summary_text += f"{message.role}: {message.content}\n"

        # Create a summary message
        summary_message = SamplingMessage(role="assistant", content=TextContent(type="text", text=summary_text))

        # Replace history with summary
        self.history = [summary_message]
