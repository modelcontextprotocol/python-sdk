# Socket Transport Examples

This directory contains examples demonstrating the socket transport feature of FastMCP. Socket transport provides a simple and efficient communication channel between client and server, similar to stdio but without stdout pollution concerns.

## Overview

The socket transport works by:
1. Client creates a TCP server and gets an available port
2. Client starts the server process, passing the port number
3. Server connects back to the client's TCP server
4. Client and server exchange messages over the TCP connection
5. When done, client closes the connection and terminates the server process

## Files

- `client.py` - Example client that:
  - Creates a TCP server
  - Starts the server process
  - Establishes MCP session
  - Calls example tools

- `server.py` - Example server that:
  - Connects to client's TCP server
  - Sets up FastMCP environment
  - Provides example tools
  - Demonstrates logging usage

## Usage

1. Run with auto-assigned port (recommended):
```bash
python client.py
```

2. Run with specific host and port:
```bash
python client.py --host localhost --port 3000
```

3. Run server directly (for testing):
```bash
python server.py --name "Echo Server" --host localhost --port 3000 --log-level DEBUG
```

## Configuration

### Client Options
- `--host` - Host to bind to (default: 127.0.0.1)
- `--port` - Port to use (default: 0 for auto-assign)

### Server Options
- `--name` - Server name
- `--host` - Host to connect to
- `--port` - Port to connect to (required)
- `--log-level` - Logging level (DEBUG/INFO/WARNING/ERROR)

## Implementation Details

### Client Features
- Automatic port assignment
- Server process management
- Connection retry logic
- Error handling
- Clean shutdown

### Server Features
- Connection retry logic
- Custom text encoding support
- Stdout/logging freedom
- Error handling
- Clean shutdown

### Error Handling
The examples demonstrate handling of:
- Connection failures and retries
- Invalid JSON messages
- Text encoding errors
- Tool execution errors
- Process lifecycle management 
