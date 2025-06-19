import json
from typing import List, Dict, Any
from dynamic_mcp_agent.llm_client import InternalAgentLLMClient
from dynamic_mcp_agent.tool_manager import ToolRegistry

class InternalLogicalAgent:
    def __init__(self, llm_client: InternalAgentLLMClient, tool_registry: ToolRegistry, max_iterations: int = 5):
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations

    async def execute_task(self, user_query: str) -> str:
        messages: List[Dict[str, Any]] = []

        system_prompt = (
            "You are a helpful and intelligent assistant capable of using tools to answer user queries. "
            "When a user asks a question, first determine if you can answer it directly. "
            "If you need to use a tool to gather information or perform an action, you will be provided with a list of available tools. "
            "Your response should be a tool call object if you need to use a tool. " # Simplified for modern tool-calling LLMs
            "After you make a tool call, you will receive the tool's output. "
            "Use this output to formulate your final answer to the user. "
            "If you can answer directly without tools, or if you have sufficient information from previous tool calls, provide a direct textual answer."
        )
        messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_query})

        print(f"InternalAgent: Starting task with query: '{user_query}'")

        for i in range(self.max_iterations):
            print(f"InternalAgent: Iteration {i + 1}/{self.max_iterations}")

            llm_tools_definition = self.tool_registry.get_tool_definitions_for_llm()

            # For logging, let's show the messages being sent (excluding system prompt for brevity sometimes)
            # print(f"InternalAgent: Sending to LLM (history): {json.dumps(messages, indent=2)}")
            # print(f"InternalAgent: Available LLM tools: {json.dumps(llm_tools_definition, indent=2)}")

            llm_response = await self.llm_client.chat_completions_create(
                messages=messages,
                tools=llm_tools_definition,
                tool_choice="auto" # Explicitly set, though client might default
            )

            if not llm_response or not llm_response.get("choices") or not llm_response["choices"][0].get("message"):
                print("Error: LLM response is not in the expected format or is empty.")
                return "Error: Received an invalid or empty response from the internal LLM."

            llm_message = llm_response["choices"][0]["message"]
            messages.append(llm_message)

            print(f"InternalAgent: Received from LLM: {json.dumps(llm_message, indent=2)}")

            if llm_message.get("tool_calls"):
                tool_calls = llm_message["tool_calls"]
                if not isinstance(tool_calls, list): # Basic validation
                    print(f"InternalAgent: Error - 'tool_calls' is not a list: {tool_calls}")
                    return "Error: LLM provided malformed tool_calls."

                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict) or not tool_call.get("id") or \
                       not isinstance(tool_call.get("function"), dict) or \
                       not tool_call["function"].get("name") or \
                       tool_call["function"].get("arguments") is None: # arguments can be empty string for some tools
                        print(f"InternalAgent: Error - Malformed tool_call object: {tool_call}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", "unknown_call_id"), # Try to get ID for context
                            "name": tool_call.get("function", {}).get("name", "unknown_function"),
                            "content": "Error: Malformed tool_call structure from LLM."
                        })
                        continue # Move to next tool call if any, or next iteration

                    tool_call_id = tool_call["id"]
                    function_name = tool_call["function"]["name"]
                    function_args_json = tool_call["function"]["arguments"]

                    print(f"InternalAgent: LLM requested call to tool '{function_name}' (Call ID: {tool_call_id}) with args: {function_args_json}")

                    try:
                        # Arguments can be an empty string if no args are needed by the tool's schema
                        parsed_args = json.loads(function_args_json) if function_args_json else {}
                        if not isinstance(parsed_args, dict):
                             raise json.JSONDecodeError("Arguments did not decode to a dictionary.", function_args_json, 0)

                        executable_function = self.tool_registry.get_executable_function(function_name)

                        tool_result = await executable_function(**parsed_args)

                        if not isinstance(tool_result, str):
                            tool_result_str = json.dumps(tool_result)
                        else:
                            tool_result_str = tool_result

                        print(f"InternalAgent: Tool '{function_name}' (Call ID: {tool_call_id}) executed. Result snippet: {tool_result_str[:250]}...")

                    except json.JSONDecodeError as e:
                        print(f"InternalAgent: Error parsing JSON arguments for tool '{function_name}' (Call ID: {tool_call_id}): {e}. Args: '{function_args_json}'")
                        tool_result_str = f"Error: Invalid JSON arguments provided for tool {function_name}: {e}. Arguments received: '{function_args_json}'"
                    except ValueError as e:
                        print(f"InternalAgent: Error with tool '{function_name}' (Call ID: {tool_call_id}): {e}")
                        tool_result_str = f"Error: Could not find or use tool {function_name}: {e}"
                    except TypeError as e: # Often indicates a mismatch in function signature and provided args
                        print(f"InternalAgent: TypeError executing tool '{function_name}' (Call ID: {tool_call_id}): {e}. Parsed args: {parsed_args if 'parsed_args' in locals() else 'not available'}")
                        tool_result_str = f"Error: Type error executing tool {function_name} (likely mismatched arguments): {e}"
                    except Exception as e:
                        print(f"InternalAgent: Unexpected error executing tool '{function_name}' (Call ID: {tool_call_id}): {e}")
                        import traceback
                        traceback.print_exc() # Print full traceback for unexpected errors
                        tool_result_str = f"Error: An unexpected error occurred while executing tool {function_name}: {type(e).__name__} - {e}"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": function_name,
                        "content": tool_result_str
                    })

            elif llm_message.get("content") is not None: # content can be an empty string
                print("InternalAgent: LLM provided final answer.")
                return llm_message["content"]
            else:
                # This case implies the LLM message had neither 'tool_calls' nor 'content'.
                # This could be valid if the 'finish_reason' is 'tool_calls' but 'tool_calls' is empty or missing,
                # which would be an LLM error. Or, if finish_reason is 'stop' but content is null.
                finish_reason = llm_response["choices"][0].get("finish_reason", "unknown")
                print(f"InternalAgent: LLM response had no direct content and no tool_calls (finish_reason: {finish_reason}). This might be an issue.")
                # If finish_reason is 'stop' but content is null, it's an empty answer.
                if finish_reason == "stop":
                    return "" # Or a specific message like "LLM provided an empty answer."
                # If finish_reason is 'tool_calls' but there are none, it's an error.
                return "Error: LLM indicated tool usage but provided no tool calls."


        print("InternalAgent: Reached maximum iterations.")
        return "Error: Agent reached maximum iterations without a final answer."

async def main():
    import asyncio
    from dynamic_mcp_agent.config import INTERNAL_LLM_BASE_URL, INTERNAL_LLM_API_KEY

    try:
        tool_reg = ToolRegistry(
            tool_config_path="dynamic_mcp_agent/tools.json",
            functions_module_name="dynamic_mcp_agent.tool_functions"
        )
    except Exception as e:
        print(f"Error initializing ToolRegistry in main: {e}")
        return

    llm_cli = InternalAgentLLMClient(
        base_url=INTERNAL_LLM_BASE_URL or "http://mock-llm-service/v1",  # Provide a default
        api_key=INTERNAL_LLM_API_KEY or "mock_api_key"
    )

    agent = InternalLogicalAgent(llm_client=llm_cli, tool_registry=tool_reg, max_iterations=3)

    test_queries = [
        "What is the list of users in the database?",
        "Can you tell me about products using SQL?",
        "Scrape the website example.com for me.",
        "What is the weather like today?" # Should be a direct answer by mock
    ]

    for i, query in enumerate(test_queries):
        print(f"\n--- Test Case {i+1}: '{query}' ---")
        try:
            response = await agent.execute_task(query)
            print(f"Final Agent Response {i+1}: {response}")
        except Exception as e:
            print(f"Error during agent execution for query '{query}': {e}")
            import traceback
            traceback.print_exc()
        print("------------------------------------")

    await llm_cli.close_session()

if __name__ == '__main__':
    # To run this example: python -m dynamic_mcp_agent.internal_agent
    # This ensures that relative imports within the dynamic_mcp_agent package work correctly.
    import asyncio
    # asyncio.run(main()) # Keep commented out for subtask runner; run manually for testing.
    pass
```
