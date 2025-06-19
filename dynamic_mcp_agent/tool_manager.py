import json
import importlib
from mcp.types import Tool as MCPTool
from typing import Callable, List, Dict, Any

class ToolRegistry:
    def __init__(self, tool_config_path: str, functions_module_name: str):
        self.tool_config_path = tool_config_path
        self.functions_module_name = functions_module_name
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._executable_functions: Dict[str, Callable] = {}
        self._load_tools()

    def _load_tools(self):
        print(f"ToolRegistry: Loading tools from '{self.tool_config_path}' using functions from '{self.functions_module_name}'")
        try:
            with open(self.tool_config_path, 'r') as f:
                tool_definitions = json.load(f)
        except FileNotFoundError:
            print(f"Error: Tool configuration file not found: {self.tool_config_path}")
            raise  # Reraise after logging, as this is a critical failure
        except json.JSONDecodeError as e:
            print(f"Error: Could not decode JSON from {self.tool_config_path}: {e}")
            raise # Reraise, as malformed JSON is a critical failure

        try:
            functions_module = importlib.import_module(self.functions_module_name)
        except ImportError as e:
            print(f"Error: Could not import functions module '{self.functions_module_name}': {e}")
            raise # Reraise, as missing module is a critical failure

        for tool_def in tool_definitions:
            tool_id = tool_def.get("id")
            if not tool_id:
                print(f"Warning: Found tool definition without an 'id'. Skipping: {tool_def}")
                continue

            executable_name = tool_def.get("executable_function_name")
            if not executable_name:
                print(f"Warning: Tool '{tool_id}' is missing 'executable_function_name'. Skipping.")
                continue

            try:
                executable_func = getattr(functions_module, executable_name)
                self._executable_functions[tool_id] = executable_func
                self._tools[tool_id] = tool_def
                print(f"ToolRegistry: Successfully loaded tool '{tool_id}' with function '{executable_name}'")
            except AttributeError:
                print(f"Warning: Executable function '{executable_name}' not found in module '{self.functions_module_name}' for tool '{tool_id}'. Skipping.")

        print(f"ToolRegistry: Loaded {len(self._tools)} tools.")

    def get_tool_definitions_for_llm(self) -> List[Dict[str, Any]]:
        """
        Formats tool definitions in a way suitable for an LLM's tool parameter.
        This typically mirrors OpenAI's function calling format.
        """
        llm_tools = []
        for tool_id, tool_def in self._tools.items():
            llm_tools.append({
                "type": "function",
                "function": {
                    "name": tool_id,
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("input_schema", {})
                }
            })
        return llm_tools

    def get_executable_function(self, tool_id: str) -> Callable:
        """
        Returns the actual Python function to be executed for a given tool_id.
        """
        func = self._executable_functions.get(tool_id)
        if not func:
            raise ValueError(f"No executable function found for tool ID: {tool_id}")
        return func

    def get_mcp_tools(self) -> List[MCPTool]:
        """
        Formats tool definitions as a list of mcp.types.Tool objects.
        Note: In this project, these low-level tools are NOT directly exposed
        via the MCP server. The server exposes a single, generic 'DynamicTaskExecutor' tool.
        This method is provided for completeness or potential internal use.
        """
        mcp_tool_list = []
        for tool_id, tool_def in self._tools.items():
            mcp_tool_list.append(MCPTool(
                name=tool_id,
                # Use 'title' if present, otherwise default to 'id'
                title=tool_def.get("title", tool_id),
                description=tool_def.get("description", ""),
                inputSchema=tool_def.get("input_schema", {})
            ))
        return mcp_tool_list

if __name__ == '__main__':
    # This block is for testing tool_manager.py directly.
    # It assumes 'tools.json' and 'tool_functions.py' are structured as per the project.
    # To run this from the project root:
    # python -m dynamic_mcp_agent.tool_manager

    # Note: Ensure dynamic_mcp_agent is in PYTHONPATH or use the -m flag.
    # The paths below assume running from the project root or that the package is installed.
    # For direct script execution, you might need to adjust PYTHONPATH if dynamic_mcp_agent is not found.
    config_path = "dynamic_mcp_agent/tools.json"
    # The module name should be the full Python import path from the project's perspective.
    functions_module = "dynamic_mcp_agent.tool_functions"

    print("Attempting to initialize ToolRegistry for testing...")
    try:
        registry = ToolRegistry(
            tool_config_path=config_path,
            functions_module_name=functions_module
        )

        print("\n--- LLM Tool Definitions (for internal LLM) ---")
        llm_formatted_tools = registry.get_tool_definitions_for_llm()
        print(json.dumps(llm_formatted_tools, indent=2))

        # The get_mcp_tools() output is less relevant for this project's architecture
        # as these tools are not directly exposed, but we can print it for verification.
        # print("\n--- MCP Tool Definitions (for reference) ---")
        # mcp_formatted_tools = registry.get_mcp_tools()
        # for mcp_tool_item in mcp_formatted_tools:
        #     # Assuming MCPTool has a Pydantic model_dump_json method or similar
        #     # For older Pydantic (v1), it might be .json(indent=2)
        #     # For Pydantic v2, it's .model_dump_json(indent=2)
        #     print(mcp_tool_item.model_dump_json(indent=2) if hasattr(mcp_tool_item, 'model_dump_json') else mcp_tool_item.json(indent=2))


        print("\n--- Getting Executable Function Example ---")
        try:
            db_func = registry.get_executable_function("query_database_tool")
            print(f"Function for 'query_database_tool': {db_func}")

            # Example of calling an async function (requires asyncio.run in a script context)
            # This part is more for illustrative purposes, as directly running async code
            # here might interfere if this script is imported elsewhere.
            # import asyncio
            # async def test_async_call():
            #     # Make sure the function is awaitable if it's async
            #     if asyncio.iscoroutinefunction(db_func):
            #         result = await db_func(sql_query="SELECT * FROM test_table_async")
            #         print(f"Test async call result for query_database_tool: {result}")
            #     else:
            #         # Handle synchronous functions if any (though our examples are async)
            #         # result = db_func(sql_query="SELECT * FROM test_table_sync")
            #         # print(f"Test sync call result for query_database_tool: {result}")
            #         print("Note: db_func is not an async function as tested here.")
            # if asyncio.iscoroutinefunction(db_func):
            #    asyncio.run(test_async_call())

        except ValueError as ve:
            print(f"Error getting executable function: {ve}")
        except Exception as e_func:
            print(f"An unexpected error occurred while trying to get/call function: {e_func}")

    except FileNotFoundError:
        print(f"Test Error: Tool configuration file '{config_path}' not found.")
        print("Make sure you are running this test from the project root directory, or the path is correct.")
    except ImportError as ie:
        print(f"Test Error: Could not import module: {functions_module}. Details: {ie}")
        print("Make sure the module path is correct, __init__.py files are present, and it's in PYTHONPATH.")
    except Exception as e:
        print(f"An unexpected error occurred during ToolRegistry example usage: {e}")
        # For more detailed debugging, you might want to print the traceback
        # import traceback
        # traceback.print_exc()
```
