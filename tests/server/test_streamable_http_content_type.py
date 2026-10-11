"""Direct unit tests for StreamableHTTPServerTransport._check_content_type.

Covers the transport-level 415 path (pragma: no cover through the public
entry, since the security middleware rejects non-JSON first) for
modelcontextprotocol/python-sdk#3670. Media types are case-insensitive
(RFC 9110 §8.3.1).
"""

import pytest
from starlette.requests import Request

from mcp.server.streamable_http import StreamableHTTPServerTransport


def make_transport() -> StreamableHTTPServerTransport:
    # _check_content_type touches no instance state; bypass __init__.
    return StreamableHTTPServerTransport.__new__(StreamableHTTPServerTransport)


def make_request(content_type: str) -> Request:
    return Request({"type": "http", "headers": [(b"content-type", content_type.encode())]})


@pytest.mark.parametrize(
    "value",
    [
        "application/json",
        "Application/JSON",
        "APPLICATION/JSON",
        "Application/JSON; Charset=UTF-8",
        "application/json; charset=utf-8",
    ],
)
def test_check_content_type_accepts_json_case_insensitive(value: str) -> None:
    assert make_transport()._check_content_type(make_request(value)) is True


@pytest.mark.parametrize("value", ["", "text/plain", "application/json-patch+json", "text/html; charset=utf-8"])
def test_check_content_type_rejects_non_json(value: str) -> None:
    assert make_transport()._check_content_type(make_request(value)) is False
