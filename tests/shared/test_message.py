from mcp.shared.transport import ServerMessageMetadata, SessionMessage, TransportContext
from mcp.types import JSONRPCRequest


def test_transport_headers_are_not_exposed_by_message_representations() -> None:
    """SDK-defined: framing metadata preserves header access without adding credentials to debug representations."""
    credential = "private-bearer-value"
    context = TransportContext(kind="http", can_send_request=False, headers={"authorization": credential})
    metadata = ServerMessageMetadata(None, None, None, None, None, False, transport_context=context)
    message = SessionMessage(JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"), metadata)
    assert metadata.transport_context is context
    assert not metadata.can_send_request
    assert credential not in repr(metadata)
    assert credential not in repr(message)
