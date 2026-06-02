"""Transport-specific interaction tests, and the in-process streaming bridge they are built on.

`StreamingASGITransport` is re-exported here as the sanctioned import point for test code
outside this suite (the bridge module itself is suite-private).
"""

from tests.interaction.transports._bridge import StreamingASGITransport

__all__ = ["StreamingASGITransport"]
