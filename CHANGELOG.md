# Changelog

## [1.3.0] - 2025-02-20

### Breaking Changes

- **Context API Changes**: The Context logging methods (info, debug, warning, error) are now async and must be awaited. ([#172](https://github.com/modelcontextprotocol/python-sdk/pull/172))
- **Resource Response Format**: Standardized resource response format to return both content and MIME type. Method `read_resource()` now returns a tuple of `(content, mime_type)` instead of just content. ([#170](https://github.com/modelcontextprotocol/python-sdk/pull/170))

### New Features

#### Lifespan Support
Added comprehensive server lifecycle management through the lifespan API:
```python
@dataclass
class AppContext:
    db: Database

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    try:
        await db.connect()
        yield AppContext(db=db)
    finally:
        await db.disconnect()

mcp = FastMCP("My App", lifespan=app_lifespan)

@mcp.tool()
def query_db(ctx: Context) -> str:
    db = ctx.request_context.lifespan_context["db"]
    return db.query()
```
([#203](https://github.com/modelcontextprotocol/python-sdk/pull/203))

#### Async Resources
Added support for async resource functions in FastMCP:
```python
@mcp.resource("users://{user_id}")
async def get_user(user_id: str) -> str:
    async with client.session() as session:
        response = await session.get(f"/users/{user_id}")
        return await response.text()
```
([#157](https://github.com/modelcontextprotocol/python-sdk/pull/157))

#### Concurrent Request Handling
Made message handling concurrent, allowing multiple requests to be processed simultaneously. ([#206](https://github.com/modelcontextprotocol/python-sdk/pull/206))

#### Request Cancellation
Added support for canceling in-flight requests and cleaning up resources. ([#167](https://github.com/modelcontextprotocol/python-sdk/pull/167))

#### Server Instructions
Added support for the `instructions` field in server initialization, allowing servers to provide usage guidance. ([#150](https://github.com/modelcontextprotocol/python-sdk/pull/150))

### Bug Fixes

- Fixed progress reporting for first tool call by correcting progress_token handling ([#176](https://github.com/modelcontextprotocol/python-sdk/pull/176))
- Fixed server crash when using debug logging ([#158](https://github.com/modelcontextprotocol/python-sdk/pull/158))
- Fixed resource template handling in FastMCP server ([#137](https://github.com/modelcontextprotocol/python-sdk/pull/137))
- Fixed MIME type preservation in resource responses ([#170](https://github.com/modelcontextprotocol/python-sdk/pull/170))
- Fixed documentation for environment variables in CLI commands ([#149](https://github.com/modelcontextprotocol/python-sdk/pull/149))
- Fixed request ID preservation in JSON-RPC responses ([#205](https://github.com/modelcontextprotocol/python-sdk/pull/205))

### Dependency Updates

- Relaxed version constraints for better compatibility:
  - `pydantic`: Changed from `>=2.10.1,<3.0.0` to `>=2.7.2,<3.0.0`
  - `pydantic-settings`: Changed from `>=2.6.1` to `>=2.5.2`
  - `uvicorn`: Changed from `>=0.30` to `>=0.23.1`
  ([#180](https://github.com/modelcontextprotocol/python-sdk/pull/180))

### Examples

- Added a simple chatbot example client to demonstrate SDK usage ([#98](https://github.com/modelcontextprotocol/python-sdk/pull/98))

### Client Improvements

- Added client support for sampling, list roots, and ping requests ([#218](https://github.com/modelcontextprotocol/python-sdk/pull/218))
- Added flexible type system for tool result returns ([#222](https://github.com/modelcontextprotocol/python-sdk/pull/222))

### Compatibility and Platform Support

- Updated URL validation to allow file and other nonstandard schemas ([#68fcf92](https://github.com/modelcontextprotocol/python-sdk/commit/68fcf92947f7d02d50340053a72a969d6bb70e1b))
- Force stdin/stdout encoding to UTF-8 for cross-platform compatibility ([#d92ee8f](https://github.com/modelcontextprotocol/python-sdk/commit/d92ee8feaa5675efddd399f3e8ebe8ed976b84c2))

### Internal Improvements

- Improved type annotations for better IDE support ([#181](https://github.com/modelcontextprotocol/python-sdk/pull/181))
- Added comprehensive tests for SSE transport ([#151](https://github.com/modelcontextprotocol/python-sdk/pull/151))
- Updated types to match 2024-11-05 MCP schema ([#165](https://github.com/modelcontextprotocol/python-sdk/pull/165))
- Refactored request and notification handling for better code organization ([#166](https://github.com/modelcontextprotocol/python-sdk/pull/166))

## [1.2.1] - 2024-01-27

### Added
- Support for async resources
- Example and test for parameter descriptions in FastMCP tools

### Fixed
- MCP install command with environment variables
- Resource template handling in FastMCP server (#129)
- Package in the generated MCP run config (#128)
- FastMCP logger debug output
- Handling of strings containing numbers in FastMCP (@sd2k, #142)

### Changed
- Refactored to use built-in typing.Annotated instead of typing_extensions
- Updated uv.lock
- Added .DS_Store to gitignore

# MCP Python SDK v1.2.0rc1 Release Notes

## Major Features

### FastMCP Integration
- Integrated [FastMCP](https://github.com/jlowin/fastmcp) as the recommended high-level server framework
- Added new `mcp.server.fastmcp` module with simplified decorator-based API
- Introduced `FastMCP` class for easier server creation and management
- Added comprehensive documentation and examples for FastMCP usage

### New CLI Package
- Added new CLI package for improved developer experience
- Introduced `mcp dev` command for local development and testing
- Added `mcp install` command for Claude Desktop integration
- Added `mcp run` command for direct server execution

## Improvements

### Documentation
- Completely revamped README with new structure and examples
- Added detailed sections on core concepts (Resources, Tools, Prompts)
- Updated documentation to recommend FastMCP as primary API
- Added sections on development workflow and deployment options
- Improved example server documentation

### Developer Experience
- Added pre-commit hooks for code quality
- Updated to Pydantic 2.10.0 for improved type checking
- Added uvicorn as a dependency for better server capabilities

## Bug Fixes
- Fixed deprecation warnings in core components
- Fixed Pydantic field handling for meta fields
- Fixed type issues throughout the codebase
- Fixed example server READMEs

## Breaking Changes
- Deprecated direct usage of `mcp.server` in favor of `mcp.server.fastmcp`
- Updated import paths for FastMCP integration
- Changed recommended installation to include CLI features (`pip install "mcp[cli]"`)

## Contributors
Special thanks to all contributors who made this release possible, including:
- Jeremiah Lowin (FastMCP)
- Oskar Raszkiewicz

**Full Changelog**: https://github.com/modelcontextprotocol/python-sdk/compare/v1.1.2...v1.2.0rc1
