from __future__ import annotations

import pytest

from mcp.shared._otel import otel_span

pytestmark = pytest.mark.anyio


def test_otel_span_creates_span():
    with otel_span("test.span", kind="CLIENT", attributes={"key": "value"}) as span:
        assert span is not None
