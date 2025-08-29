import pytest

from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    ClientRequest,
    Implementation,
    InitializeRequest,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCRequest,
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


@pytest.mark.anyio
async def test_method_initialization():
    """
    Test that the method is automatically set on object creation.
    Testing just for InitializeRequest to keep the test simple, but should be set for other types as well.
    """
    initialize_request = InitializeRequest(
        params=InitializeRequestParams(
            protocolVersion=LATEST_PROTOCOL_VERSION,
            capabilities=ClientCapabilities(),
            clientInfo=Implementation(
                name="mcp",
                version="0.1.0",
            ),
        )
    )

    assert initialize_request.method == "initialize", "method should be set to 'initialize'"
    assert initialize_request.params is not None
    assert initialize_request.params.protocolVersion == LATEST_PROTOCOL_VERSION
