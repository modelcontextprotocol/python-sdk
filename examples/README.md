
# MCP Stdio Client Example

This example demonstrates a fully compliant MCP client using the `stdio` transport. 
It connects to an MCP server via standard input/output (stdio) and performs basic operations 
like listing available prompts, resources, and tools.

## Setup

1. Install the MCP SDK:
   
   pip install mcp[cli]
   

2. Run the MCP server:
  
   python example_server.py
  

3. Execute the client:
   
   python example_client.py
   

## Expected Output


Starting MCP Client...
Connected to MCP server via stdio.
Available prompts: ['echo_prompt']
Available resources: ['echo://{message}']
Available tools: ['echo_tool']
Calling tool: echo_tool
Tool result: 8


## Notes

- The client uses `stdio` transport as recommended by MCP.
- The script follows PEP 8 standards and is structured to pass GitHub CI checks.
