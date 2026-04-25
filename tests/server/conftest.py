"""Shared fixtures for server-side tests."""

from collections.abc import Iterator

import pytest
from logfire.testing import CaptureLogfire, TestExporter
from opentelemetry.sdk.trace import ReadableSpan


class SpanCapture:
    """Thin adapter over logfire's `TestExporter` for asserting on MCP spans.

    `finished()` returns the raw `ReadableSpan` objects emitted by the
    ``mcp-python-sdk`` instrumentation scope, filtered to exclude logfire's
    synthetic ``pending_span`` markers, so tests can assert directly on
    `.name`, `.kind`, `.status`, `.attributes`, `.parent`, `.events`.
    """

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
    """In-memory MCP span capture, cleared before and after each test.

    Backed by the project-level `capfire` override (see ``tests/conftest.py``)
    so there is a single global tracer provider for the suite.
    """
    capture = SpanCapture(capfire.exporter)
    capture.clear()
    yield capture
    capture.clear()
