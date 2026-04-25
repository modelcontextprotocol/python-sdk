"""Shared fixtures for server-side tests."""

from collections.abc import Iterator

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_span_exporter = InMemorySpanExporter()


@pytest.fixture(scope="session")
def _tracer_provider() -> TracerProvider:
    """Install a real OTel SDK tracer provider once per test session.

    The runtime dependency is ``opentelemetry-api`` only, which yields no-op
    ``NonRecordingSpan`` objects. Tests that need to assert on emitted spans
    request the `spans` fixture, which depends on this one to make the global
    tracer record into an in-memory exporter.
    """
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_span_exporter))
    trace.set_tracer_provider(provider)
    return provider


@pytest.fixture
def spans(_tracer_provider: TracerProvider) -> Iterator[InMemorySpanExporter]:
    """In-memory OTel span exporter, cleared before and after each test."""
    _span_exporter.clear()
    yield _span_exporter
    _span_exporter.clear()
