# MCP Simple Chatbot

This example demonstrates how to integrate the Model Context Protocol (MCP) into a simple CLI chatbot. The implementation showcases MCP's flexibility by supporting multiple tools through MCP servers and is compatible with any LLM provider that follows OpenAI API standards.

## Requirements

- Python 3.10
- `python-dotenv`
- `requests`
- `mcp`
- `uvicorn`

## Installation

1. **Install the dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**

   Create a `.env` file in the root directory and add your API key:

   ```plaintext
   LLM_API_KEY=your_api_key_here
   ```

3. **Configure servers:**

   The `servers_config.json` follows the same structure as Claude Desktop, allowing for easy integration of multiple servers. 
   Here's an example:

   ```json
   {
     "mcpServers": {
       "sqlite": {
         "command": "uvx",
         "args": ["mcp-server-sqlite", "--db-path", "./test.db"]
       },
       "puppeteer": {
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-puppeteer"]
       }
     }
   }
   ```
   Environment variables are supported as well. Pass them as you would with the Claude Desktop App.

   Example:
   ```json
   {
     "mcpServers": {
       "server_name": {
         "command": "uvx",
         "args": ["mcp-server-name", "--additional-args"],
         "env": {
           "API_KEY": "your_api_key_here"
         }
       }
     }
   }
   ```

## Usage

1. **Run the client:**

   ```bash
   python main.py
   ```

2. **Interact with the assistant:**
   
   The assistant will automatically detect available tools and can respond to queries based on the tools provided by the configured servers.

3. **Exit the session:**

   Type `quit` or `exit` to end the session.

## Architecture

- **Tool Discovery**: Tools are automatically discovered from configured servers.
- **System Prompt**: Tools are dynamically included in the system prompt, allowing the LLM to understand available capabilities.
- **Server Integration**: Supports any MCP-compatible server, tested with various server implementations including Uvicorn and Node.js.

### Class Structure
- **Configuration**: Manages environment variables and server configurations
- **Server**: Handles MCP server initialization, tool discovery, and execution
- **Tool**: Represents individual tools with their properties and formatting
- **LLMClient**: Manages communication with the LLM provider
- **ChatSession**: Orchestrates the interaction between user, LLM, and tools

### Logic Flow

1. **Tool Integration**:
   - Tools are dynamically discovered from MCP servers
   - Tool descriptions are automatically included in system prompt
   - Tool execution is handled through standardized MCP protocol

2. **Runtime Flow**:
   - User input is received
   - Input is sent to LLM with context of available tools
   - LLM response is parsed:
     - If it's a tool call → execute tool and return result
     - If it's a direct response → return to user
   - Tool results are sent back to LLM for interpretation
   - Final response is presented to user


