import aiohttp
import json
import uuid # For generating unique IDs
import time

class InternalAgentLLMClient:
    def __init__(self, base_url: str, api_key: str, session: aiohttp.ClientSession = None):
        self.base_url = base_url
        self.api_key = api_key
        self._session = session
        self._should_close_session = False # Flag to indicate if this instance owns the session

        if self._session is None:
            # If no session is provided, create one and take ownership
            self._session = aiohttp.ClientSession()
            self._should_close_session = True
        # If a session is provided, this instance does NOT own it.

    async def close_session(self):
        # Only close the session if this instance created (owns) it.
        if self._session and self._should_close_session and not self._session.closed:
            await self._session.close()
            print("InternalAgentLLMClient: Closed internally managed session.")
        elif self._session and not self._should_close_session:
            print("InternalAgentLLMClient: Using externally managed session, not closing it here.")

    async def chat_completions_create(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> dict:
        """
        Simulates a call to a chat completion API with tool calling capability.
        Actual implementation would make an HTTP request to self.base_url.
        """
        print(f"MockLLMClient: Received messages: {messages}")
        print(f"MockLLMClient: Available tools: {tools}")
        print(f"MockLLMClient: Tool choice: {tool_choice}")

        last_message = messages[-1] if messages else {}
        response_id = "chatcmpl-" + str(uuid.uuid4())

        # Simulate current Unix timestamp
        created_timestamp = int(time.time())

        # Default response: simple text reply
        llm_response_content = "I am a mock LLM. I processed your query."
        finish_reason = "stop"
        tool_calls = None

        if last_message.get("role") == "user":
            user_content = last_message.get("content", "").lower()
            if "database" in user_content or "sql" in user_content:
                print("MockLLMClient: Simulating database_tool call")
                tool_call_id = "call_" + str(uuid.uuid4())
                tool_calls = [{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": "query_database_tool",
                        # Simulate a generic query, actual query would come from LLM based on user input
                        "arguments": json.dumps({"sql_query": "SELECT * FROM users;"})
                    }
                }]
                llm_response_content = None
                finish_reason = "tool_calls"
            elif "website" in user_content or "scrape" in user_content:
                print("MockLLMClient: Simulating scrape_web_tool call")
                tool_call_id = "call_" + str(uuid.uuid4())
                tool_calls = [{
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": "scrape_web_tool",
                        # Simulate a generic URL, actual URL would come from LLM
                        "arguments": json.dumps({"url": "https://example.com"})
                    }
                }]
                llm_response_content = None
                finish_reason = "tool_calls"
            # Add more keyword-based tool call simulations here if needed

        elif last_message.get("role") == "tool":
            tool_name = last_message.get("name", "the tool")
            tool_content_preview = last_message.get("content", "")[:70] + "..." if last_message.get("content") else "no content"
            print(f"MockLLMClient: Received tool response for tool_call_id: {last_message.get('tool_call_id')} from tool {tool_name}")
            llm_response_content = f"Okay, I have processed the result from {tool_name} (which returned: '{tool_content_preview}') and here is your final answer."
            finish_reason = "stop"

        # Construct the full response object
        response_message = {"role": "assistant"}
        if llm_response_content is not None:
            response_message["content"] = llm_response_content

        if tool_calls:
            response_message["tool_calls"] = tool_calls
            # Ensure content is None if there are tool_calls, as per OpenAI spec for some models
            # However, some models might return content even with tool_calls, so this can be flexible.
            # For strict adherence to a model that expects null content with tool_calls:
            response_message["content"] = None


        response = {
            "id": response_id,
            "object": "chat.completion",
            "created": created_timestamp,
            "model": "mock-llm-v1", # Or a more specific mock model name
            "choices": [{
                "index": 0,
                "message": response_message,
                "finish_reason": finish_reason
            }]
        }

        print(f"MockLLMClient: Sending response: {json.dumps(response, indent=2)}")
        return response

# Example usage (optional, for testing the client directly)
async def main():
    import asyncio
    # Example: Using the client
    # Note: In a real app, base_url and api_key would come from config.py
    # For the mock, these can be dummy values if not used for actual HTTP calls
    client = InternalAgentLLMClient(base_url="http://mockserver:1234/v1", api_key="mock_key")

    # Simulate a user query that should trigger the database tool
    messages_db = [{"role": "user", "content": "Can you query the database for all users?"}]
    tools_available = [{ # This structure matches OpenAI's format
        "type": "function",
        "function": {
            "name": "query_database_tool",
            "description": "Queries a database with the given SQL query.",
            "parameters": { # Schema for the tool's expected arguments
                "type": "object",
                "properties": {"sql_query": {"type": "string", "description": "The SQL query to execute."}},
                "required": ["sql_query"]
            }
        }
    }]
    print("\n--- Simulating DB Tool Call ---")
    response_db = await client.chat_completions_create(messages=messages_db, tools=tools_available)
    print("\nResponse from LLM (DB query):")
    print(json.dumps(response_db, indent=2))

    # Simulate a tool response and getting a final answer
    if response_db["choices"][0]["message"].get("tool_calls"):
        tool_call = response_db["choices"][0]["message"]["tool_calls"][0]

        # Construct the history including the assistant's tool call request and the tool's response
        messages_tool_response = messages_db + [ # Original user message
            response_db["choices"][0]["message"], # Assistant's message asking to call the tool
            {"role": "tool", "tool_call_id": tool_call["id"], "name": tool_call["function"]["name"], "content": "{\"status\": \"success\", \"row_count\": 3, \"data_preview\": [{\"user_id\": 1, \"name\": \"Alice\"}]}"}
        ]

        print("\n--- Simulating Final Answer after Tool Call ---")
        final_response = await client.chat_completions_create(messages=messages_tool_response, tools=tools_available)
        print("\nResponse from LLM (Final Answer):")
        print(json.dumps(final_response, indent=2))

    # Simulate a generic query
    print("\n--- Simulating Generic Query ---")
    messages_generic = [{"role": "user", "content": "Hello, how are you?"}]
    response_generic = await client.chat_completions_create(messages=messages_generic, tools=tools_available)
    print("\nResponse from LLM (Generic):")
    print(json.dumps(response_generic, indent=2))

    await client.close_session()

if __name__ == "__main__":
    # To run this example: python dynamic_mcp_agent/llm_client.py
    # This setup is to allow running the main async function.
    # Note: If running in an environment that manages its own asyncio loop (like Jupyter),
    # you might need to use `await main()` instead of `asyncio.run(main())`.
    # For simple script execution, asyncio.run() is standard.
    # import asyncio # Already imported in main()
    # asyncio.run(main())
    pass # Keep 'pass' to ensure the file can be imported without running main automatically
         # The subtask runner might try to import or execute files, so avoid auto-executing asyncio.run.
```
