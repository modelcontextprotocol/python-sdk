from typing import List, Union
from agentops.logging import logger
from agentops.semconv import (
    SpanAttributes,
    MessageAttributes,
)
from agentops.instrumentation.common.attributes import (
    AttributeMap,
    IndexedAttributeMap,
    _extract_attributes_from_mapping,
    _extract_attributes_from_mapping_with_index,
)

try:
    from openai.types.responses import (
        FunctionTool,
        WebSearchTool,
        FileSearchTool,
        ComputerTool,
        Response,
        ResponseUsage,
        ResponseReasoningItem,
        ResponseOutputMessage,
        ResponseOutputText,
        ResponseFunctionToolCall,
        ResponseFunctionWebSearch,
        ResponseFileSearchToolCall,
        ResponseComputerToolCall,
    )
    from openai.types.responses.response_usage import InputTokensDetails, OutputTokensDetails

    ToolTypes = Union[
        FunctionTool,
        WebSearchTool,
        FileSearchTool,
    ]
    ResponseOutputTypes = Union[
        ResponseOutputMessage,
        ResponseOutputText,
        ResponseFunctionToolCall,
        ResponseFunctionWebSearch,
        ResponseComputerToolCall,
        ResponseFileSearchToolCall,
    ]
except ImportError as e:
    logger.debug(f"[agentops.instrumentation.openai_agents] Could not import OpenAI Agents SDK types: {e}")


RESPONSE_ATTRIBUTES: AttributeMap = {
    # Response(
    #     id='resp_67ddd0196a4c81929f7e3783a80f18110b486458d6766f93',
    #     created_at=1742589977.0,
    #     error=None,
    #     incomplete_details=None,
    #     instructions='You are a helpful assistant...',
    #     metadata={},
    #     model='gpt-4o-2024-08-06',
    #     object='response',
    #     output=[
    #         ...
    #     ],
    #     parallel_tool_calls=True,
    #     temperature=1.0,
    #     tool_choice='auto',
    #     tools=[
    #         ...)
    #     ],
    #     top_p=1.0,
    #     max_output_tokens=None,
    #     previous_response_id=None,
    #     reasoning=Reasoning(
    #         ...
    #     ),
    #     status='completed',
    #     text=ResponseTextConfig(format=ResponseFormatText(type='text')),
    #     truncation='disabled',
    #     usage=ResponseUsage(
    #         ...
    #     ),
    #     user=None,
    #     store=True
    # )
    SpanAttributes.LLM_RESPONSE_ID: "id",
    SpanAttributes.LLM_REQUEST_MODEL: "model",
    SpanAttributes.LLM_RESPONSE_MODEL: "model",
    SpanAttributes.LLM_OPENAI_RESPONSE_INSTRUCTIONS: "instructions",
    SpanAttributes.LLM_REQUEST_MAX_TOKENS: "max_output_tokens",
    SpanAttributes.LLM_REQUEST_TEMPERATURE: "temperature",
    SpanAttributes.LLM_REQUEST_TOP_P: "top_p",
}


RESPONSE_TOOL_ATTRIBUTES: IndexedAttributeMap = {
    # FunctionTool(
    #     name='get_weather',
    #     parameters={'properties': {'location': {'title': 'Location', 'type': 'string'}}, 'required': ['location'], 'title': 'get_weather_args', 'type': 'object', 'additionalProperties': False},
    #     strict=True,
    #     type='function',
    #     description='Get the current weather for a location.'
    # )
    MessageAttributes.TOOL_CALL_TYPE: "type",
    MessageAttributes.TOOL_CALL_NAME: "name",
    MessageAttributes.TOOL_CALL_DESCRIPTION: "description",
    MessageAttributes.TOOL_CALL_ARGUMENTS: "parameters",
    # TODO `strict` is not converted
}


RESPONSE_TOOL_WEB_SEARCH_ATTRIBUTES: IndexedAttributeMap = {
    # WebSearchTool(
    #     type='web_search_preview',
    #     search_context_size='medium',
    #     user_location=UserLocation(
    #         type='approximate',
    #         city=None,
    #         country='US',
    #         region=None,
    #         timezone=None
    #     )
    # )
    MessageAttributes.TOOL_CALL_NAME: "type",
    # `parameters` is added by the `get_response_tool_web_search_attributes` function,
    # which contains `search_context_size` and `user_location`.
    MessageAttributes.TOOL_CALL_ARGUMENTS: "parameters",
}


RESPONSE_TOOL_FILE_SEARCH_ATTRIBUTES: IndexedAttributeMap = {
    # FileSearchTool(
    #     type='file_search',
    #     vector_store_ids=['store_123', 'store_456'],
    #     filters=Filters(
    #         key='value'
    #     ),
    #     max_num_results=10,
    #     ranking_options=RankingOptions(
    #         ranker='default-2024-11-15',
    #         score_threshold=0.8
    #     )
    # )
    MessageAttributes.TOOL_CALL_TYPE: "type",
    # `parameters` is added by the `get_response_tool_file_search_attributes` function,
    # which contains `vector_store_ids`, `filters`, `max_num_results`, and `ranking_options`.
    MessageAttributes.TOOL_CALL_ARGUMENTS: "parameters",
}


RESPONSE_TOOL_COMPUTER_ATTRIBUTES: IndexedAttributeMap = {
    # ComputerTool(
    #     display_height=1080.0,
    #     display_width=1920.0,
    #     environment='mac',
    #     type='computer_use_preview'
    # )
    MessageAttributes.TOOL_CALL_TYPE: "type",
    # `parameters` is added by the `get_response_tool_computer_attributes` function,
    # which contains `display_height`, `display_width`, `environment`, etc.
    MessageAttributes.TOOL_CALL_ARGUMENTS: "parameters",
}


RESPONSE_OUTPUT_MESSAGE_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseOutputMessage(
    #     id='msg_67ddcad3b6008192b521035d8b71fc570db7bfce93fd916a',
    #     content=[
    #         ...
    #     ],
    #     role='assistant',
    #     status='completed',
    #     type='message'
    # )
    MessageAttributes.COMPLETION_ID: "id",
    MessageAttributes.COMPLETION_TYPE: "type",
    MessageAttributes.COMPLETION_ROLE: "role",
    MessageAttributes.COMPLETION_FINISH_REASON: "status",
}


RESPONSE_OUTPUT_TEXT_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseOutputText(
    #     annotations=[],
    #     text='Recursion is a programming technique ...',
    #     type='output_text'
    # )
    MessageAttributes.COMPLETION_TYPE: "type",
    MessageAttributes.COMPLETION_CONTENT: "text",
    # TODO `annotations` are not converted
}


RESPONSE_OUTPUT_REASONING_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseReasoningItem(
    #     id='reasoning_12345',
    #     summary=[
    #         Summary(
    #             text='The model used a step-by-step approach to solve the problem.',
    #             type='summary_text'
    #         )
    #     ],
    #     type='reasoning',
    #     status='completed'
    # )
    MessageAttributes.COMPLETION_ID: "id",
    MessageAttributes.COMPLETION_TYPE: "type",
    MessageAttributes.COMPLETION_FINISH_REASON: "status",
    # TODO `summary` is not converted
}


RESPONSE_OUTPUT_TOOL_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseFunctionToolCall(
    #     id='ftc_67ddcad3b6008192b521035d8b71fc570db7bfce93fd916a',
    #     arguments='{"location": "New York"}',
    #     call_id='call_12345',
    #     name='get_weather',
    #     type='function_call',
    #     status='completed'
    # )
    MessageAttributes.COMPLETION_TOOL_CALL_ID: "id",
    MessageAttributes.COMPLETION_TOOL_CALL_TYPE: "type",
    MessageAttributes.COMPLETION_TOOL_CALL_NAME: "name",
    MessageAttributes.COMPLETION_TOOL_CALL_ARGUMENTS: "arguments",
    # TODO `status` & `call_id` are not converted
}


RESPONSE_OUTPUT_TOOL_WEB_SEARCH_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseFunctionWebSearch(
    #     id='ws_67eda37a5f18819280bf8b64f315bfa70091ec39ac46b411',
    #     status='completed',
    #     type='web_search_call'
    # )
    MessageAttributes.COMPLETION_TOOL_CALL_ID: "id",
    MessageAttributes.COMPLETION_TOOL_CALL_TYPE: "type",
    MessageAttributes.COMPLETION_TOOL_CALL_STATUS: "status",
}

RESPONSE_OUTPUT_TOOL_WEB_SEARCH_URL_ANNOTATIONS: IndexedAttributeMap = {
    # AnnotationURLCitation(
    #     end_index=747,
    #     start_index=553,
    #     title="You can now play a real-time AI-rendered Quake II in your browser",
    #     type='url_citation',
    #     url='https://www.tomshardware.com/video-games/you-can-now-play-a-real-time-ai-rendered-quake-ii-in-your-browser-microsofts-whamm-offers-generative-ai-for-games?utm_source=openai'
    # )
    MessageAttributes.COMPLETION_ANNOTATION_END_INDEX: "end_index",
    MessageAttributes.COMPLETION_ANNOTATION_START_INDEX: "start_index",
    MessageAttributes.COMPLETION_ANNOTATION_TITLE: "title",
    MessageAttributes.COMPLETION_ANNOTATION_TYPE: "type",
    MessageAttributes.COMPLETION_ANNOTATION_URL: "url",
}


RESPONSE_OUTPUT_TOOL_COMPUTER_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseComputerToolCall(
    #     id='comp_12345',
    #     action=Action(
    #         type='click',
    #         target='button_submit'
    #     ),
    #     call_id='call_67890',
    #     pending_safety_checks=[
    #         PendingSafetyCheck(
    #             type='check_type',
    #             status='pending'
    #         )
    #     ],
    #     status='completed',
    #     type='computer_call'
    # )
    # TODO semantic conventions for `ResponseComputerToolCall` are not defined yet
}


RESPONSE_OUTPUT_TOOL_FILE_SEARCH_ATTRIBUTES: IndexedAttributeMap = {
    # ResponseFileSearchToolCall(
    #     id='fsc_12345',
    #     queries=['example query'],
    #     status='completed',
    #     type='file_search_call',
    #     results=[
    #         Result(
    #             attributes={'key1': 'value1', 'key2': 42},
    #             file_id='file_67890',
    #             filename='example.txt',
    #             score=0.95,
    #             text='Example text retrieved from the file.'
    #         ),
    #         ...
    #     ]
    # )
    # TODO semantic conventions for `ResponseFileSearchToolCall` are not defined yet
}


RESPONSE_USAGE_ATTRIBUTES: AttributeMap = {
    SpanAttributes.LLM_USAGE_COMPLETION_TOKENS: "output_tokens",
    SpanAttributes.LLM_USAGE_PROMPT_TOKENS: "input_tokens",
    SpanAttributes.LLM_USAGE_TOTAL_TOKENS: "total_tokens",
}


# usage attributes are shared with `input_details_tokens` and `output_details_tokens`
RESPONSE_USAGE_DETAILS_ATTRIBUTES: AttributeMap = {
    SpanAttributes.LLM_USAGE_CACHE_READ_INPUT_TOKENS: "cached_tokens",
    SpanAttributes.LLM_USAGE_REASONING_TOKENS: "reasoning_tokens",
}


RESPONSE_REASONING_ATTRIBUTES: AttributeMap = {
    # Reasoning(
    #    effort='medium',
    #    generate_summary=None,
    # )
    # TODO `effort` and `generate_summary` need semantic conventions
}


def get_response_kwarg_attributes(kwargs: dict) -> AttributeMap:
    """Handles interpretation of openai Responses.create method keyword arguments."""

    # Just gather the attributes that are not present in the Response object
    # TODO We could gather more here and have more context available in the
    # event of an error during the request execution.

    # Method signature for `Responses.create`:
    # input: Union[str, ResponseInputParam],
    # model: Union[str, ChatModel],
    # include: Optional[List[ResponseIncludable]] | NotGiven = NOT_GIVEN,
    # instructions: Optional[str] | NotGiven = NOT_GIVEN,
    # max_output_tokens: Optional[int] | NotGiven = NOT_GIVEN,
    # metadata: Optional[Metadata] | NotGiven = NOT_GIVEN,
    # parallel_tool_calls: Optional[bool] | NotGiven = NOT_GIVEN,
    # previous_response_id: Optional[str] | NotGiven = NOT_GIVEN,
    # reasoning: Optional[Reasoning] | NotGiven = NOT_GIVEN,
    # store: Optional[bool] | NotGiven = NOT_GIVEN,
    # stream: Optional[Literal[False]] | NotGiven = NOT_GIVEN,
    # temperature: Optional[float] | NotGiven = NOT_GIVEN,
    # text: ResponseTextConfigParam | NotGiven = NOT_GIVEN,
    # tool_choice: response_create_params.ToolChoice | NotGiven = NOT_GIVEN,
    # tools: Iterable[ToolParam] | NotGiven = NOT_GIVEN,
    # top_p: Optional[float] | NotGiven = NOT_GIVEN,
    # truncation: Optional[Literal["auto", "disabled"]] | NotGiven = NOT_GIVEN,
    # user: str | NotGiven = NOT_GIVEN,
    # extra_headers: Headers | None = None,
    # extra_query: Query | None = None,
    # extra_body: Body | None = None,
    # timeout: float | httpx.Timeout | None | NotGiven = NOT_GIVEN,
    attributes = {}

    # `input` can either be a `str` or a list of many internal types, so we duck
    # type our way into some usable common attributes
    _input: Union[str, list, None] = kwargs.get("input")
    if isinstance(_input, str):
        attributes[MessageAttributes.PROMPT_ROLE.format(i=0)] = "user"
        attributes[MessageAttributes.PROMPT_CONTENT.format(i=0)] = _input

    elif isinstance(_input, list):
        for i, prompt in enumerate(_input):
            # Object type is pretty diverse, so we handle common attributes, but do so
            # conditionally because not all attributes are guaranteed to exist
            if hasattr(prompt, "type"):
                attributes[MessageAttributes.PROMPT_TYPE.format(i=i)] = prompt.type
            if hasattr(prompt, "role"):
                attributes[MessageAttributes.PROMPT_ROLE.format(i=i)] = prompt.role
            if hasattr(prompt, "content"):
                attributes[MessageAttributes.PROMPT_CONTENT.format(i=i)] = prompt.content

    else:
        logger.debug(f"[agentops.instrumentation.openai.response] '{type(_input)}' is not a recognized input type.")

    # `model` is always `str` (`ChatModel` type is just a string literal)
    attributes[SpanAttributes.LLM_REQUEST_MODEL] = str(kwargs.get("model"))

    return attributes


# We call this `response_response` because in OpenAI Agents the `Response` is
# a return type from the `responses` module
def get_response_response_attributes(response: "Response") -> AttributeMap:
    """Handles interpretation of an openai Response object."""
    attributes = _extract_attributes_from_mapping(response.__dict__, RESPONSE_ATTRIBUTES)

    if response.output:
        attributes.update(get_response_output_attributes(response.output))

    if response.tools:
        attributes.update(get_response_tools_attributes(response.tools))

    if response.reasoning:
        attributes.update(_extract_attributes_from_mapping(response.reasoning.__dict__, RESPONSE_REASONING_ATTRIBUTES))

    if response.usage:
        attributes.update(get_response_usage_attributes(response.usage))

    return attributes


def get_response_output_attributes(output: List["ResponseOutputTypes"]) -> AttributeMap:
    """Handles interpretation of an openai Response `output` list."""
    attributes = {}

    for i, output_item in enumerate(output):
        if isinstance(output_item, ResponseOutputMessage):
            attributes.update(get_response_output_message_attributes(i, output_item))

        elif isinstance(output_item, ResponseReasoningItem):
            attributes.update(
                _extract_attributes_from_mapping_with_index(output_item, RESPONSE_OUTPUT_REASONING_ATTRIBUTES, i)
            )

        elif isinstance(output_item, ResponseFunctionToolCall):
            attributes.update(
                _extract_attributes_from_mapping_with_index(output_item, RESPONSE_OUTPUT_TOOL_ATTRIBUTES, i=i, j=0)
            )

        elif isinstance(output_item, ResponseFunctionWebSearch):
            attributes.update(
                _extract_attributes_from_mapping_with_index(
                    output_item, RESPONSE_OUTPUT_TOOL_WEB_SEARCH_ATTRIBUTES, i=i, j=0
                )
            )

        elif isinstance(output_item, ResponseComputerToolCall):
            attributes.update(
                _extract_attributes_from_mapping_with_index(
                    output_item, RESPONSE_OUTPUT_TOOL_COMPUTER_ATTRIBUTES, i=i, j=0
                )
            )

        elif isinstance(output_item, ResponseFileSearchToolCall):
            attributes.update(
                _extract_attributes_from_mapping_with_index(
                    output_item, RESPONSE_OUTPUT_TOOL_FILE_SEARCH_ATTRIBUTES, i=i, j=0
                )
            )

        else:
            logger.debug(f"[agentops.instrumentation.openai.response] '{output_item}' is not a recognized output type.")

    return attributes


def get_response_output_text_attributes(output_text: "ResponseOutputText", index: int) -> AttributeMap:
    """Handles interpretation of an openai ResponseOutputText object."""
    # This function is a helper to handle the ResponseOutputText type specifically
    attributes = _extract_attributes_from_mapping_with_index(output_text, RESPONSE_OUTPUT_TEXT_ATTRIBUTES, index)

    if hasattr(output_text, "annotations"):
        for j, output_text_annotation in enumerate(output_text.annotations):
            attributes.update(
                _extract_attributes_from_mapping_with_index(
                    output_text_annotation, RESPONSE_OUTPUT_TOOL_WEB_SEARCH_URL_ANNOTATIONS, i=index, j=j
                )
            )

    return attributes


def get_response_output_message_attributes(index: int, message: "ResponseOutputMessage") -> AttributeMap:
    """Handles interpretation of an openai ResponseOutputMessage object."""
    attributes = _extract_attributes_from_mapping_with_index(message, RESPONSE_OUTPUT_MESSAGE_ATTRIBUTES, index)

    if message.content:
        for i, content in enumerate(message.content):
            if isinstance(content, ResponseOutputText):
                attributes.update(get_response_output_text_attributes(content, i))

            else:
                logger.debug(
                    f"[agentops.instrumentation.openai.response] '{content}' is not a recognized content type."
                )

    return attributes


def get_response_tools_attributes(tools: List["ToolTypes"]) -> AttributeMap:
    """Handles interpretation of openai Response `tools` list."""
    attributes = {}

    for i, tool in enumerate(tools):
        if isinstance(tool, FunctionTool):
            attributes.update(_extract_attributes_from_mapping_with_index(tool, RESPONSE_TOOL_ATTRIBUTES, i))

        elif isinstance(tool, WebSearchTool):
            attributes.update(get_response_tool_web_search_attributes(tool, i))

        elif isinstance(tool, FileSearchTool):
            attributes.update(get_response_tool_file_search_attributes(tool, i))

        elif isinstance(tool, ComputerTool):
            attributes.update(get_response_tool_computer_attributes(tool, i))

        else:
            logger.debug(f"[agentops.instrumentation.openai.response] '{tool}' is not a recognized tool type.")

    return attributes


def get_response_tool_web_search_attributes(tool: "WebSearchTool", index: int) -> AttributeMap:
    """Handles interpretation of an openai WebSearchTool object."""
    parameters = {}
    if hasattr(tool, "search_context_size"):
        parameters["search_context_size"] = tool.search_context_size

    if hasattr(tool, "user_location") and tool.user_location is not None:
        parameters["user_location"] = tool.user_location.__dict__

    tool_data = tool.__dict__
    if parameters:
        # add parameters to the tool_data dict so we can format them with the other attributes
        tool_data["parameters"] = parameters

    return _extract_attributes_from_mapping_with_index(tool_data, RESPONSE_TOOL_WEB_SEARCH_ATTRIBUTES, index)


def get_response_tool_file_search_attributes(tool: "FileSearchTool", index: int) -> AttributeMap:
    """Handles interpretation of an openai FileSearchTool object."""
    parameters = {}

    if hasattr(tool, "vector_store_ids"):
        parameters["vector_store_ids"] = tool.vector_store_ids

    if hasattr(tool, "filters") and tool.filters is not None:
        parameters["filters"] = tool.filters.__dict__

    if hasattr(tool, "max_num_results"):
        parameters["max_num_results"] = tool.max_num_results

    if hasattr(tool, "ranking_options") and tool.ranking_options is not None:
        parameters["ranking_options"] = tool.ranking_options.__dict__

    tool_data = tool.__dict__
    if parameters:
        # add parameters to the tool_data dict so we can format them with the other attributes
        tool_data["parameters"] = parameters

    return _extract_attributes_from_mapping_with_index(tool_data, RESPONSE_TOOL_FILE_SEARCH_ATTRIBUTES, index)


def get_response_tool_computer_attributes(tool: "ComputerTool", index: int) -> AttributeMap:
    """Handles interpretation of an openai ComputerTool object."""
    parameters = {}

    if hasattr(tool, "display_height"):
        parameters["display_height"] = tool.display_height

    if hasattr(tool, "display_width"):
        parameters["display_width"] = tool.display_width

    if hasattr(tool, "environment"):
        parameters["environment"] = tool.environment

    tool_data = tool.__dict__
    if parameters:
        # add parameters to the tool_data dict so we can format them with the other attributes
        tool_data["parameters"] = parameters

    return _extract_attributes_from_mapping_with_index(tool_data, RESPONSE_TOOL_COMPUTER_ATTRIBUTES, index)


def get_response_usage_attributes(usage: "ResponseUsage") -> AttributeMap:
    """Handles interpretation of an openai ResponseUsage object."""
    # ResponseUsage(
    #     input_tokens=0,
    #     output_tokens=0,
    #     output_tokens_details=OutputTokensDetails(reasoning_tokens=0),
    #     total_tokens=0,
    #     input_tokens_details={'cached_tokens': 0}
    # )
    attributes = {}

    attributes.update(_extract_attributes_from_mapping(usage.__dict__, RESPONSE_USAGE_ATTRIBUTES))

    # input_tokens_details is an `InputTokensDetails` object or `dict` if it exists
    if hasattr(usage, "input_tokens_details"):
        input_details = usage.input_tokens_details
        if input_details is None:
            pass

        elif isinstance(input_details, InputTokensDetails):
            attributes.update(
                _extract_attributes_from_mapping(input_details.__dict__, RESPONSE_USAGE_DETAILS_ATTRIBUTES)
            )

        elif isinstance(input_details, dict):  # openai-agents often returns a dict for some reason.
            attributes.update(_extract_attributes_from_mapping(input_details, RESPONSE_USAGE_DETAILS_ATTRIBUTES))

        else:
            logger.debug(
                f"[agentops.instrumentation.openai.response] '{input_details}' is not a recognized input details type."
            )

    # output_tokens_details is an `OutputTokensDetails` object
    output_details = usage.output_tokens_details
    if output_details is None:
        pass

    elif isinstance(output_details, OutputTokensDetails):
        attributes.update(_extract_attributes_from_mapping(output_details.__dict__, RESPONSE_USAGE_DETAILS_ATTRIBUTES))

    else:
        logger.debug(
            f"[agentops.instrumentation.openai.response] '{output_details}' is not a recognized output details type."
        )

    return attributes
