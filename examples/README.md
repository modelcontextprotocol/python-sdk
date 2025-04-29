# SSE Client Demo

## Description
This example demonstrates how to use the Model Context Protocol (MCP) Python SDK with Server-Sent Events (SSE) transport.

It sets up a local mock MCP server using Flask and connects a simple SSE client to receive streamed events.

## How to Run
Install required packages:
   ```bash
   pip install flask requests

Start the server and client:
python mcp_server_client_demo.py
Alternatively, you can:

Run mock_mcp_server.py separately to start the server.

Then run sse_client_demo.py to connect the client.

You should see three streamed messages printed from the server to the client.
