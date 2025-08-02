import pytest
from pydantic import AnyUrl

from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    PROMPT_SCHEME,
    TOOL_SCHEME,
    ClientRequest,
    Implementation,
    JSONRPCMessage,
    JSONRPCRequest,
    Prompt,
    Resource,
    Tool,
)


@pytest.mark.anyio
async def test_jsonrpc_request():
    json_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {"batch": None, "sampling": None},
            "clientInfo": {"name": "mcp", "version": "0.1.0"},
        },
    }

    request = JSONRPCMessage.model_validate(json_data)
    assert isinstance(request.root, JSONRPCRequest)
    ClientRequest.model_validate(request.model_dump(by_alias=True, exclude_none=True))

    assert request.root.jsonrpc == "2.0"
    assert request.root.id == 1
    assert request.root.method == "initialize"
    assert request.root.params is not None
    assert request.root.params["protocolVersion"] == LATEST_PROTOCOL_VERSION


def test_implementation_no_uri():
    """Test that Implementation doesn't have URI field."""
    impl = Implementation(name="test-server", version="1.0.0")
    assert impl.name == "test-server"
    assert impl.version == "1.0.0"
    assert not hasattr(impl, "uri")


def test_resource_uri():
    """Test that Resource requires URI and validates scheme."""
    # Resource should require URI
    with pytest.raises(ValueError):
        Resource(name="test")  # pyright: ignore[reportCallIssue]

    # This should work
    resource = Resource(name="test", uri=AnyUrl("file://test.txt"))
    assert resource.name == "test"
    assert str(resource.uri) == "file://test.txt/"  # AnyUrl adds trailing slash

    # Should reject TOOL_SCHEME and PROMPT_SCHEME schemes
    with pytest.raises(ValueError, match="reserved schemes"):
        Resource(name="test", uri=AnyUrl(f"{TOOL_SCHEME}/test"))

    with pytest.raises(ValueError, match="reserved schemes"):
        Resource(name="test", uri=AnyUrl(f"{PROMPT_SCHEME}/test"))


def test_tool_uri_validation():
    """Test that Tool requires URI with tool scheme."""
    # Tool requires URI with TOOL_SCHEME
    tool = Tool(name="calculator", inputSchema={"type": "object"}, uri=f"{TOOL_SCHEME}/calculator")
    assert tool.name == "calculator"
    assert str(tool.uri) == f"{TOOL_SCHEME}/calculator"

    # Should reject non-tool schemes
    with pytest.raises(ValueError):
        Tool(name="calculator", inputSchema={"type": "object"}, uri="custom://calc")


def test_prompt_uri_validation():
    """Test that Prompt requires URI with prompt scheme."""
    # Prompt requires URI with PROMPT_SCHEME
    prompt = Prompt(name="greeting", uri=f"{PROMPT_SCHEME}/greeting")
    assert prompt.name == "greeting"
    assert str(prompt.uri) == f"{PROMPT_SCHEME}/greeting"

    # Should reject non-prompt schemes
    with pytest.raises(ValueError):
        Prompt(name="greeting", uri="custom://greet")
