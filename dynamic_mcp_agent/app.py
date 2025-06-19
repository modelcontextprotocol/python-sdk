import asyncio
import aiohttp
from contextlib import asynccontextmanager
import json # For pretty printing test outputs

from mcp.server.fastmcp import FastMCP, Context as MCPContext

# Configuration and Clients
from dynamic_mcp_agent import config
from dynamic_mcp_agent.llm_client import InternalAgentLLMClient
from dynamic_mcp_agent.tool_manager import ToolRegistry
from dynamic_mcp_agent.internal_agent import InternalLogicalAgent

# Lifespan manager for shared resources
@asynccontextmanager
async def app_lifespan(mcp_app: FastMCP):
    print("APP_LIFESPAN: Initializing application resources...")
    shared_aiohttp_session = aiohttp.ClientSession()

    llm_base_url = config.INTERNAL_LLM_BASE_URL if config.INTERNAL_LLM_BASE_URL else "http://mockllm/v1"
    llm_api_key = config.INTERNAL_LLM_API_KEY if config.INTERNAL_LLM_API_KEY else "mock_key"

    llm_client = InternalAgentLLMClient(
        base_url=llm_base_url,
        api_key=llm_api_key,
        session=shared_aiohttp_session
    )

    try:
        tool_registry = ToolRegistry(
            tool_config_path="dynamic_mcp_agent/tools.json",
            functions_module_name="dynamic_mcp_agent.tool_functions"
        )
    except Exception as e:
        print(f"APP_LIFESPAN: CRITICAL - Failed to initialize ToolRegistry: {e}")
        if not shared_aiohttp_session.closed:
            await shared_aiohttp_session.close()
        raise RuntimeError(f"Failed to initialize ToolRegistry: {e}") from e

    mcp_app.state.llm_client = llm_client
    mcp_app.state.tool_registry = tool_registry

    print("APP_LIFESPAN: Resources initialized.")
    try:
        yield
    finally:
        print("APP_LIFESPAN: Cleaning up application resources...")
        if hasattr(mcp_app.state, 'llm_client') and mcp_app.state.llm_client:
            await mcp_app.state.llm_client.close_session()

        if shared_aiohttp_session and not shared_aiohttp_session.closed:
            print("APP_LIFESPAN: Closing shared aiohttp session.")
            await shared_aiohttp_session.close()

        print("APP_LIFESPAN: Resources cleaned up.")

# Create the FastMCP server instance
mcp_server = FastMCP(
    name="DynamicTaskExecutorHost",
    instructions="This server provides a dynamic task executor. Provide a natural language query, and the internal agent will attempt to fulfill it using available tools.",
    lifespan=app_lifespan
)

@mcp_server.tool(
    name="dynamic_task_executor",
    title="Dynamic Task Executor",
    description="Executes a natural language query using an internal agent and dynamically loaded tools. Input should be a single string representing the query."
)
async def dynamic_task_executor_impl(query: str, mcp_ctx: MCPContext) -> str:
    print(f"MCP_TOOL (dynamic_task_executor): Received query: '{query}'")

    if not hasattr(mcp_ctx.fastmcp.state, 'llm_client') or \
       not hasattr(mcp_ctx.fastmcp.state, 'tool_registry'):
        print("Error: LLM client or Tool Registry not found in app state. Check lifespan function.")
        return "Error: Core server components are not initialized. Please contact the administrator."

    llm_client: InternalAgentLLMClient = mcp_ctx.fastmcp.state.llm_client
    tool_registry: ToolRegistry = mcp_ctx.fastmcp.state.tool_registry

    agent = InternalLogicalAgent(llm_client=llm_client, tool_registry=tool_registry)

    try:
        final_response = await agent.execute_task(user_query=query)
        print(f"MCP_TOOL (dynamic_task_executor): Agent finished. Response snippet: '{final_response[:200]}...'")
        return final_response
    except Exception as e:
        print(f"MCP_TOOL (dynamic_task_executor): Error during agent execution: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc()
        return f"Error: An unexpected error occurred while processing your query. Please check server logs for details. Error type: {type(e).__name__}"

# Local test function and main execution block
async def run_local_integration_tests(mcp_app_instance: FastMCP):
    print("\n--- RUNNING LOCAL INTEGRATION TESTS ---")

    # Manually enter the lifespan context to ensure app.state is populated
    async with app_lifespan(mcp_app_instance):
        # Create a mock MCPContext for the tests
        # The key part is mcp_ctx.fastmcp.state which should mirror what FastMCP provides
        class MockFastMCPState:
            def __init__(self):
                # Access the already initialized components from the mcp_app_instance
                self.llm_client = mcp_app_instance.state.llm_client
                self.tool_registry = mcp_app_instance.state.tool_registry

        class MockFastMCP:
            def __init__(self):
                self.state = MockFastMCPState()

        class MockMCPContext(MCPContext): # Inherit from MCPContext for type compatibility
            def __init__(self):
                self.fastmcp = MockFastMCP()
                # Add other fields if dynamic_task_executor_impl uses them from mcp_ctx
                # For now, only fastmcp.state seems to be used.
                self.event = asyncio.Event() # Example, if used by some MCP features
                self.extra = {}

        mock_ctx = MockMCPContext()

        test_queries = [
            "Get all users from the database.",
            "Scrape the website example.com for its content.",
            "What is the capital of France?",
            # This query will test the mock LLM's ability to respond after one tool call,
            # as it's not currently set up for multi-step tool reasoning.
            "Tell me about products in the database then scrape example.com then tell me about users in the database"
        ]

        for i, test_query in enumerate(test_queries):
            print(f"\n--- Test Case {i+1}: Query: '{test_query}' ---")
            try:
                response = await dynamic_task_executor_impl(test_query, mock_ctx)
                print(f"Test Response {i+1}:")
                try:
                    # Try to parse and pretty-print if JSON, else print as string
                    parsed_json = json.loads(response)
                    print(json.dumps(parsed_json, indent=2))
                except json.JSONDecodeError:
                    print(response)
            except Exception as e:
                print(f"Error during test query '{test_query}': {e}")
                import traceback
                traceback.print_exc()
            print("-------------------------------------------")

    print("\n--- LOCAL INTEGRATION TESTS COMPLETE ---")

if __name__ == "__main__":
    # Option 1: Run local tests
    # This will be the default action when running `python -m dynamic_mcp_agent.app`
    print("Executing main: Running local integration tests...")
    asyncio.run(run_local_integration_tests(mcp_server))
    print("\nLocal integration tests finished. To run the actual server, you would typically use a different entry point or command.")

    # Option 2: Run the actual server (e.g., for manual stdio or HTTP)
    # To run the server, you would typically comment out the asyncio.run(run_local_integration_tests(mcp_server)) line above
    # and uncomment one of the server run commands below.
    # For example, to run with stdio:
    # print("\nStarting Dynamic MCP Agent server with STDIN/STDOUT transport...")
    # print("Run 'mcp chat stdio:/' in another terminal to connect.")
    # try:
    #     mcp_server.run(transport="stdio")
    # except RuntimeError as e:
    #     print(f"Failed to start server: {e}")
    # except Exception as e:
    #     print(f"An unexpected error occurred during server startup: {e}")
    #     import traceback
    #     traceback.print_exc()

    # Or for HTTP:
    # import uvicorn
    # print("\nStarting Dynamic MCP Agent server with StreamableHTTP transport on port 8000...")
    # print("Run 'mcp chat http://127.0.0.1:8000/mcp' in another terminal to connect.")
    # try:
    #     uvicorn.run(
    #         mcp_server.streamable_http_app(),
    #         host="127.0.0.1",
    #         port=8000,
    #         log_level="info"
    #     )
    # except RuntimeError as e:
    #     print(f"Failed to start StreamableHTTP server: {e}")
    # except Exception as e:
    #     print(f"An unexpected error occurred during StreamableHTTP server startup: {e}")
    #     import traceback
    #     traceback.print_exc()

```
