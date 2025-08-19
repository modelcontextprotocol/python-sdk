# MCP Python SDK

A Python implementation of the Model Context Protocol (MCP) that enables applications to provide context for LLMs in a standardized way.

## Examples

The [Examples](examples-quickstart.md) section provides working code examples covering many aspects of MCP development. Each code example in these documents corresponds to an example .py file in the examples/ directory in the repository.

- [Getting started](examples-quickstart.md): Quick introduction to FastMCP and basic server patterns
- [Server development](examples-server-tools.md): Tools, resources, prompts, and structured output examples
- [Transport protocols](examples-transport-http.md): HTTP and streamable transport implementations
- [Low-level servers](examples-lowlevel-servers.md): Advanced patterns using the low-level server API
- [Authentication](examples-authentication.md): OAuth 2.1 server and client implementations
- [Client development](examples-clients.md): Complete client examples with various connection types

## API Reference

Complete API documentation is auto-generated from the source code and available in the [API Reference](reference/mcp/index.md) section.

## Code example index

### Servers

| File | Transport | Resources | Prompts | Tools | Completions | Sampling | Elicitation | Progress | Logging | Authentication | Configuration |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [Complex input handling](examples-server-tools.md#complex-input-handling) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Desktop integration](examples-server-tools.md#desktop-integration) | stdio | ✅ | — | ✅ | — | — | — | — | — | — | — |
| [Enhanced echo server](examples-echo-servers.md#enhanced-echo-server) | stdio | ✅ | ✅ | ✅ | — | — | — | — | — | — | — |
| [Memory and state management](examples-server-resources.md#memory-and-state-management) | stdio | — | — | ✅ | — | — | — | — | — | — | ✅ |
| [Parameter descriptions](examples-server-tools.md#parameter-descriptions) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Basic readme example](examples-quickstart.md#basic-readme-example) | stdio | ✅ | — | ✅ | — | — | — | — | — | — | — |
| [Screenshot tools](examples-server-tools.md#screenshot-tools) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Simple echo server](examples-echo-servers.md#simple-echo-server) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Text processing tools](examples-server-tools.md#text-processing-tools) | stdio | — | — | ✅ | — | — | — | — | — | — | ✅ |
| [Unicode and internationalization](examples-server-tools.md#unicode-and-internationalization) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Weather service with structured output](examples-structured-output.md#weather-service-with-structured-output) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Complete authentication server](examples-authentication.md#complete-authentication-server) | stdio | — | — | — | — | — | — | — | — | ✅ | — |
| [Legacy Authorization Server](examples-authentication.md#legacy-authorization-server) | streamable-http | — | — | ✅ | — | — | — | — | — | ✅ | ✅ |
| [Resource server with introspection](examples-authentication.md#resource-server-with-introspection) | streamable-http | — | — | ✅ | — | — | — | — | — | ✅ | ✅ |
| [Simple prompt server](examples-server-prompts.md#simple-prompt-server) | stdio | — | ✅ | — | — | — | — | — | — | — | — |
| [Simple resource server](examples-server-resources.md#simple-resource-server) | stdio | ✅ | — | — | — | — | — | — | — | — | — |
| [Stateless HTTP server](examples-transport-http.md#stateless-http-server) | streamable-http | — | — | ✅ | — | — | — | — | ✅ | — | ✅ |
| [Stateful HTTP server](examples-transport-http.md#stateful-http-server) | streamable-http | — | — | ✅ | — | — | — | — | ✅ | — | ✅ |
| [Simple tool server](examples-lowlevel-servers.md#simple-tool-server) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Low-level structured output](examples-structured-output.md#low-level-structured-output) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Basic prompts](examples-server-prompts.md#basic-prompts) | stdio | — | ✅ | — | — | — | — | — | — | — | — |
| [Basic resources](examples-server-resources.md#basic-resources) | stdio | ✅ | — | — | — | — | — | — | — | — | — |
| [Basic tools](examples-server-tools.md#basic-tools) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Completion support](examples-server-advanced.md#completion-support) | stdio | ✅ | ✅ | — | ✅ | — | — | — | — | — | — |
| [Direct execution](examples-quickstart.md#direct-execution) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [User interaction and elicitation](examples-server-advanced.md#user-interaction-and-elicitation) | stdio | — | — | ✅ | — | — | ✅ | — | — | — | — |
| [FastMCP quickstart](examples-quickstart.md#fastmcp-quickstart) | stdio | ✅ | ✅ | ✅ | — | — | — | — | — | — | — |
| [Image handling](examples-server-advanced.md#image-handling) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Lifespan management](examples-server-advanced.md#lifespan-management) | stdio | — | — | ✅ | — | — | — | — | — | — | ✅ |
| [Basic low-level server](examples-lowlevel-servers.md#basic-low-level-server) | stdio | — | ✅ | — | — | — | — | — | — | — | — |
| [Low-level server with lifespan](examples-lowlevel-servers.md#low-level-server-with-lifespan) | stdio | — | — | ✅ | — | — | — | — | — | — | ✅ |
| [Low-level structured output](examples-structured-output.md#low-level-structured-output) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Logging and notifications](examples-server-advanced.md#logging-and-notifications) | stdio | — | — | ✅ | — | — | — | — | ✅ | — | — |
| [OAuth server implementation](examples-authentication.md#oauth-server-implementation) | streamable-http | — | — | ✅ | — | — | — | — | — | ✅ | — |
| [LLM sampling and integration](examples-server-advanced.md#llm-sampling-and-integration) | stdio | — | — | ✅ | — | ✅ | — | — | — | — | — |
| [Streamable HTTP configuration](examples-transport-http.md#streamable-http-configuration) | streamable-http | — | — | ✅ | — | — | — | — | — | — | ✅ |
| [Mounting multiple servers](examples-transport-http.md#mounting-multiple-servers) | streamable-http | — | — | ✅ | — | — | — | — | — | — | ✅ |
| [FastMCP structured output](examples-structured-output.md#fastmcp-structured-output) | stdio | — | — | ✅ | — | — | — | — | — | — | — |
| [Tools with context and progress reporting](examples-server-tools.md#tools-with-context-and-progress-reporting) | stdio | — | — | ✅ | — | — | — | ✅ | ✅ | — | — |


### Clients

| File | Transport | Resources | Prompts | Tools | Completions | Sampling | Authentication |
|---|---|---|---|---|---|---|---|
| [Authentication client](examples-clients.md#authentication-client) | streamable-http | — | — | ✅ | — | — | ✅ |
| [Complete chatbot client](examples-clients.md#complete-chatbot-client) | stdio | — | — | ✅ | — | — | — |
| [Completion client](examples-clients.md#completion-client) | stdio | ✅ | ✅ | — | ✅ | — | — |
| [Display utilities](examples-clients.md#display-utilities) | stdio | ✅ | — | ✅ | — | — | — |
| [OAuth authentication client](examples-clients.md#oauth-authentication-client) | streamable-http | ✅ | — | ✅ | — | — | ✅ |
| [Tool result parsing](examples-clients.md#tool-result-parsing) | stdio | — | — | ✅ | — | — | — |
| [Basic stdio client](examples-clients.md#basic-stdio-client) | stdio | ✅ | ✅ | ✅ | — | ✅ | — |
| [Streamable HTTP client](examples-clients.md#streamable-http-client) | streamable-http | — | — | ✅ | — | — | — |

Notes:

- **Resources** for clients indicates the example uses the Resources API (reading resources or listing resource templates).
- **Completions** refers to the completion/complete API for argument autocompletion.
- **Sampling** indicates the example exercises the sampling/createMessage flow (server-initiated in server examples; client-provided callback in stdio_client).
- **Authentication** indicates OAuth support is implemented in the example.
- Em dash (—) indicates **not demonstrated** in the example.
