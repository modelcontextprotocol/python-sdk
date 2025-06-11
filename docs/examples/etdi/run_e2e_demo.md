# End-to-End Demo (`run_e2e_demo.py`)

This page documents the actual features and steps demonstrated by the `run_e2e_demo.py` script in the ETDI examples.

## What the Demo Does

The script demonstrates the following implemented features:

- **Tool Registration/Provider SDK**: Shows how to register tools (with and without OAuth), update tool versions, and manage permissions using the ETDI ToolProvider SDK.
- **Custom OAuth Provider Support**: Demonstrates integration with both Auth0 and custom OAuth providers for tool authentication.
- **Event System**: Registers event listeners and emits events for tool verification, approval, and security violations.
- **MCP Tool Discovery**: Uses the ETDI client to connect to MCP servers, discover tools, and display security-level filtering and verification.
- **Security Features**: Runs a secure client demo that demonstrates attack prevention and security policy enforcement.

## How to Run the Demo

1. Ensure you are in the project root directory and have activated your Python virtual environment.
2. Navigate to the `examples/etdi/` directory if needed.
3. Run the script:

```bash
python examples/etdi/run_e2e_demo.py
```

The script will sequentially run each feature demonstration and print the results to the console, including success/failure for each step.

## Output

You will see output for:
- Tool registration and provider statistics
- OAuth provider configuration
- Event system activity
- MCP tool discovery and client stats
- Security feature demonstration results
- A summary of which demonstrations succeeded or failed

For more details, see the script source at `examples/etdi/run_e2e_demo.py`. 