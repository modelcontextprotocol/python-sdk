# Basic ETDI Usage (`basic_usage.py`)

This page documents the actual features and steps demonstrated by the `basic_usage.py` script in the ETDI examples.

## What the Example Does

The script demonstrates the following implemented features:

- **ETDI Client Initialization**: Shows how to configure and initialize an ETDI client with OAuth authentication and security settings.
- **Tool Discovery**: Discovers available tools from the MCP server and displays their verification status, provider, and permissions.
- **Tool Verification and Approval**: Verifies a discovered tool, checks if it is approved, and approves it if necessary.
- **Version Change Detection**: Checks if a tool's version has changed and notifies if re-approval is required.
- **Tool Invocation**: Attempts to invoke a verified and approved tool (will fail without a real MCP server, as expected in the demo).

## How to Run the Example

1. Ensure you are in the project root directory and have activated your Python virtual environment.
2. Navigate to the `examples/etdi/` directory if needed.
3. Run the script:

```bash
python examples/etdi/basic_usage.py
```

The script will print the results of each step to the console, including tool discovery, verification, approval, and (attempted) invocation.

## Output

You will see output for:
- ETDI client initialization and stats
- Tool discovery and listing
- Tool verification and approval
- Version change detection
- Tool invocation attempt and result

For more details, see the script source at `examples/etdi/basic_usage.py`. 