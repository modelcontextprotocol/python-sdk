# Python SDK ETDI Examples

This section provides various examples demonstrating the capabilities and usage of the Enhanced Tool Definition Interface (ETDI) Python SDK.

## Categories

-   **[ETDI Core Examples](./etdi/index.md)**: Demonstrations of core ETDI security features, server and client implementations, and specific attack prevention mechanisms. These examples showcase how ETDI enhances the security of tool-based interactions.
    -   Includes detailed walkthroughs of features like call stack security, OAuth integration, and cryptographic verification of tools.
    -   See individual example pages like [`run_e2e_demo.md`](./etdi/run_e2e_demo.md) or [`basic_usage.md`](./etdi/basic_usage.md).

-   **[FastMCP Integration Example](../fastmcp/index.md)**: Showcases how to integrate ETDI security features seamlessly with the FastMCP decorator API.
    -   Focuses on the ease of adding security flags like `etdi=True`, `etdi_permissions`, and call stack constraints directly in `@server.tool()` decorators.

## Overview of Key Examples

Below is a summary of some important examples. Please refer to the specific sub-sections linked above for a complete list and detailed explanations.

### End-to-End Security Demo

-   **File**: `examples/etdi/run_e2e_demo.py`
-   **Documentation**: [`docs/examples/etdi/run_e2e_demo.md`](./etdi/run_e2e_demo.md)
-   **Description**: A comprehensive demonstration of ETDI features, including attack prevention, secure client-server interaction, and enforcement of security policies.

### FastMCP with ETDI

-   **File**: `examples/fastmcp/etdi_fastmcp_example.py`
-   **Documentation**: [`docs/fastmcp/index.md`](../fastmcp/index.md)
-   **Description**: Illustrates how to easily enable and configure ETDI security measures (permissions, call stack limits) using FastMCP decorators.

### Tool Poisoning Prevention

-   **Directory**: `examples/etdi/tool_poisoning_demo/`
-   **Documentation**: [`docs/examples/etdi/tool_poisoning_demo.md`](./etdi/tool_poisoning_demo.md)
-   **Description**: Demonstrates how ETDI prevents tool poisoning attacks by verifying tool authenticity and integrity.

### Request Signing Examples

- **File**: `examples/etdi/request_signing_example.py`
  - **Description**: Demonstrates client-side request signing using RSA/ECDSA algorithms.
- **File**: `examples/etdi/request_signing_server_example.py`
  - **Description**: Shows server-side signature verification for incoming requests.
- **File**: `examples/etdi/comprehensive_request_signing_example.py`
  - **Description**: Provides an end-to-end workflow for request signing and verification between client and server.

## Navigating the Examples

-   Each major example or category has its own index page within the `docs/examples/` directory.
-   Python source code for these examples can be found in the `examples/` directory at the root of the project.
-   The documentation pages aim to explain the purpose, key features, and how to run each example.

Explore these examples to gain a practical understanding of how to leverage the ETDI Python SDK for building secure and robust tool-enabled applications. 