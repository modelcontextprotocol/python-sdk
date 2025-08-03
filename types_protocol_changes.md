# Protocol Changes in types.py

## URI Standardization

### Added URI schemes
```python
MCP_SCHEME = "mcp"
TOOL_SCHEME = "mcp://tools"
PROMPT_SCHEME = "mcp://prompts"
```

## Request/Response Changes

### Renamed pagination to list-based naming
```python
# Before
class PaginatedRequestParams(RequestParams):
    cursor: Cursor | None = None

class PaginatedRequest(Request[PaginatedRequestParams | None, MethodT])
class PaginatedResult(Result)

# After
class ListRequestParams(RequestParams):
    prefix: str | None = None  # NEW: prefix filtering
    cursor: Cursor | None = None

class ListRequest(Request[ListRequestParams | None, MethodT])
class ListResult(Result)
```

## Tool Protocol Changes

### Tool now includes URI
```python
class Tool(BaseMetadata):
    uri: AnyUrl | None = None  # NEW: auto-generated as mcp://tools/{name}
    description: str | None = None
    inputSchema: dict[str, Any]
```

## Prompt Protocol Changes

### Prompt now includes URI
```python
class Prompt(BaseMetadata):
    uri: AnyUrl | None = None  # NEW: auto-generated as mcp://prompts/{name}
    description: str | None = None
    arguments: list[PromptArgument] | None = None
```

## Resource Validation

### Resources cannot use tool/prompt URI schemes
```python
@model_validator(mode="after")
def validate_uri_scheme(self) -> "Resource":
    # Prevents resources from using mcp://tools or mcp://prompts
```

## List Methods Update

All list requests now support prefix filtering:
- `ListResourcesRequest`
- `ListToolsRequest` 
- `ListPromptsRequest`
- `ListResourceTemplatesRequest`