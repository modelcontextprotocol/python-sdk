"""
Example script demonstrating how to use the Model Context Protocol (MCP) Python SDK
with Server-Sent Events (SSE) transport.
"""
from modelcontext.client import MCPClient
from modelcontext.transport.sse import SSETransport

SERVER_URL = "http://localhost:5000"

def main():
    transport = SSETransport(base_url=SERVER_URL)
    client = MCPClient(transport=transport)

    try:
        response = client.request(
            tool="example_tool",
            input={"message": "Hello via SSE!"}
        )
        print("Response:", response)
    except Exception as e:
        print("An error occurred:", e)

if __name__ == "__main__":
    main()
