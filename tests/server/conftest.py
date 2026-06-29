from collections.abc import Iterator

import pytest
from logfire.testing import CaptureLogfire, TestExporter
from opentelemetry.sdk.trace import ReadableSpan


class SpanCapture:
    """Adapter over logfire's `TestExporter`; `finished()` excludes logfire's synthetic `pending_span` markers."""

    def __init__(self, exporter: TestExporter) -> None:
        self._exporter = exporter

    def clear(self) -> None:
        self._exporter.clear()

    def finished(self) -> list[ReadableSpan]:
        return [
            s
            for s in self._exporter.exported_spans
            if s.instrumentation_scope is not None
            and s.instrumentation_scope.name == "mcp-python-sdk"
            and not (s.attributes and s.attributes.get("logfire.span_type") == "pending_span")
        ]


@pytest.fixture
def spans(capfire: CaptureLogfire) -> Iterator[SpanCapture]:
    """MCP span capture, cleared before and after each test.

    Backed by the `capfire` override in `tests/conftest.py`, which scopes
    `mcp.shared._otel._tracer` to the test so it doesn't leak into later tests.
    """
    capture = SpanCapture(capfire.exporter)
    capture.clear()
    yield capture
    capture.clear()
