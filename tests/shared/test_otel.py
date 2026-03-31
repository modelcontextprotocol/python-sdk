from __future__ import annotations

from unittest.mock import patch

import pytest

from mcp.shared._otel import _get_tracer, otel_span

pytestmark = pytest.mark.anyio


def test_otel_span_creates_span():
    _get_tracer.cache_clear()
    with otel_span("test.span", kind="CLIENT", attributes={"key": "value"}) as span:
        assert span is not None


def test_otel_span_noop_when_unavailable():
    _get_tracer.cache_clear()
    with patch.dict("sys.modules", {"opentelemetry": None, "opentelemetry.trace": None}):
        _get_tracer.cache_clear()
        with otel_span("test.span") as span:
            assert span is None
    _get_tracer.cache_clear()
