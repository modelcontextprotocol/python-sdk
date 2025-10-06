"""Define a simple MCP client that supports sampling."""

import asyncio
import http
import json

import openai
import pydantic_settings
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)

import mcp
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.context import RequestContext
from mcp.types import CreateMessageRequestParams, CreateMessageResult, ErrorData, TextContent, Tool


class Configurations(pydantic_settings.BaseSettings):
    """Define configurations for the sampling client."""

    chat_model: str = "gpt-4o-mini"
    max_tokens: int = 1024
    mcp_server_host: str = "localhost"
    mcp_server_port: int = 8000
    openai_api_key: str = "your_openai_api_key"
    system_prompt: str = "You are a helpful assistant."

    model_config = pydantic_settings.SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


class SamplingClient:
    """Define a simple MCP client that supports sampling.

    Parameters
    ----------
    config : Configurations
        The configurations for the sampling client.
    """

    def __init__(self: "SamplingClient", config: Configurations) -> None:
        self.config = config

        self.server_url = f"http://{self.config.mcp_server_host}:{self.config.mcp_server_port}/mcp"
        self.openai_client = openai.OpenAI(api_key=self.config.openai_api_key)

        self.conversation_history: list[ChatCompletionMessageParam] = []

    def get_openai_response(
        self: "SamplingClient",
        chat_history: list[ChatCompletionMessageParam],
        system_prompt: str,
        max_tokens: int,
        tools: list[ChatCompletionToolParam] | None = None,
    ) -> ChatCompletion:
        """Get a non-streaming response from OpenAI API.

        Parameters
        ----------
        chat_history : list[ChatCompletionMessageParam]
            The chat history to use for the chat completion.
        system_prompt : str
            The system prompt to use for the chat completion.
        max_tokens : int
            The maximum number of tokens to generate in the response.
        tools : list[ChatCompletionToolParam] | None, optional
            The tools to use for the chat completion, by default None.

        Returns
        -------
        ChatCompletion
            The response from the OpenAI API.
        """
        updated_chat_history = [
            ChatCompletionSystemMessageParam(content=system_prompt, role="system"),
            *chat_history,
        ]

        extra_arguments = {} if tools is None else {"tool_choice": "auto", "tools": tools}

        chat_completion = self.openai_client.chat.completions.create(
            messages=updated_chat_history,
            model=self.config.chat_model,
            max_completion_tokens=max_tokens,
            n=1,
            stream=False,
            **extra_arguments,
        )

        return chat_completion

    async def fetch_mcp_tools(self: "SamplingClient") -> list[Tool]:
        """List available tools."""
        async with streamablehttp_client(self.server_url) as (read_stream, write_stream, _):
            async with mcp.ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                server_tools = await session.list_tools()

        return server_tools.tools

    @staticmethod
    def convert_to_openai_tools(mcp_tools: list[Tool]) -> list[ChatCompletionToolParam]:
        """Convert MCP tools to OpenAI tool call parameters.

        Parameters
        ----------
        mcp_tools : list[Tool]
            List of MCP tools to convert.

        Returns
        -------
        list[ChatCompletionToolParam]
            List of OpenAI tool call parameters.
        """
        return [
            ChatCompletionToolParam(
                function={
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
                type="function",
            )
            for tool in mcp_tools
        ]

    async def sampling_handler(
        self: "SamplingClient", context: RequestContext, parameters: CreateMessageRequestParams
    ) -> CreateMessageResult | ErrorData:
        """Handle sampling requests for OpenAI API calls with MCP tools.

        Parameters
        ----------
        context : RequestContext
            request context containing information about the sampling request
        parameters : CreateMessageRequestParams
            parameters for the sampling request, including messages and customisations

        Returns
        -------
        CreateMessageResult | ErrorData
            result of the sampling request, either a message result or an error data
        """
        del context

        openai_response = self.get_openai_response(
            [
                ChatCompletionUserMessageParam(
                    content=(
                        message.content.text if isinstance(message.content, TextContent) else str(message.content)
                    ),
                    role="user",
                )
                for message in parameters.messages
            ],
            parameters.systemPrompt or self.config.system_prompt,
            parameters.maxTokens,
        )

        if not (choices := openai_response.choices):
            return ErrorData(
                code=http.HTTPStatus.INTERNAL_SERVER_ERROR,
                message="No choices returned from OpenAI API.",
            )

        choice = choices[0]
        sampling_response_message = choice.message.content or ""

        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text=sampling_response_message),
            model=self.config.chat_model,
            stopReason=choice.finish_reason,
        )

    async def execute_tool_call(self: "SamplingClient", tool_name: str, arguments: dict) -> str:
        """Execute a tool call on an MCP server.

        Parameters
        ----------
        tool_name : str
            name of the tool to call, formatted as "mcp-{server_name}-{tool_name}"
        arguments : dict
            arguments to pass to the tool call

        Returns
        -------
        str
            JSON string containing the result of the tool call or an error message
        """
        async with streamablehttp_client(self.server_url) as (read_stream, write_stream, _):
            async with mcp.ClientSession(read_stream, write_stream, sampling_callback=self.sampling_handler) as session:
                await session.initialize()

                tool_result = await session.call_tool(tool_name, arguments=arguments)

        if tool_result.isError:
            error_message = "".join(content.text for content in tool_result.content if isinstance(content, TextContent))

            return json.dumps({"error": (f"Failed tool call to {tool_name=} with {arguments=}: {error_message}.")})

        if (structured_result := tool_result.structuredContent) is not None:
            return json.dumps(structured_result)

        return json.dumps([element.model_dump() for element in tool_result.content])

    async def orchestrate(self: "SamplingClient", user_message: str) -> None:
        """Orchestrate the sampling client to handle requests."""
        self.conversation_history.append(ChatCompletionUserMessageParam(role="user", content=user_message))

        self.mcp_server_tools = await self.fetch_mcp_tools()
        self.openai_compatible_tools = self.convert_to_openai_tools(self.mcp_server_tools)

        openai_response = self.get_openai_response(
            self.conversation_history,
            self.config.system_prompt,
            self.config.max_tokens,
            tools=self.openai_compatible_tools,
        )

        if not (choices := openai_response.choices):
            error_message = "No choices returned from OpenAI API."
            self.conversation_history.append(
                ChatCompletionAssistantMessageParam(role="assistant", content=error_message)
            )

            print(error_message)

            return

        choice = choices[0]

        while choice.finish_reason == "tool_calls":
            for tool_call in choice.message.tool_calls or []:
                if tool_call.type != "function":
                    continue

                tool_response = await self.execute_tool_call(
                    tool_call.function.name, json.loads(tool_call.function.arguments)
                )

                self.conversation_history.append(
                    ChatCompletionAssistantMessageParam(
                        role="assistant",
                        content=f"Tool {tool_call.id} returned: {tool_response}",
                    )
                )

            openai_response = self.get_openai_response(
                self.conversation_history,
                self.config.system_prompt,
                self.config.max_tokens,
                tools=self.openai_compatible_tools,
            )

            if not (choices := openai_response.choices):
                error_message = "No choices returned from OpenAI API."
                self.conversation_history.append(
                    ChatCompletionAssistantMessageParam(role="assistant", content=error_message)
                )

                print(error_message)

                return

            choice = choices[0]

        assistant_message = choice.message.content or ""
        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        print(f"Assistant: {choice.message.content}")


def main():
    """Run the sampling client."""
    config = Configurations()

    sampling_client = SamplingClient(config)

    user_message = input("User: ")
    while user_message.lower() not in {"exit", "quit"}:
        asyncio.run(sampling_client.orchestrate(user_message))

        user_message = input("User: ")


if __name__ == "__main__":
    main()
