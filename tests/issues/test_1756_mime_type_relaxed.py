"""Test for GitHub issue #1756: Relax MIME type validation in FastMCP resources.

The previous MIME type validation used a restrictive regex pattern that rejected
valid MIME types per RFC 2045. For example, quoted parameter values like
'text/plain; charset="utf-8"' were rejected.

The fix replaces the regex with a lightweight validator that only checks for the
minimal type/subtype structure (presence of '/'), aligning with the MCP spec
which defines mimeType as an optional string with no format constraints.
"""

import pytest

from mcp.server.mcpserver.resources.types import FunctionResource


def _dummy() -> str:  # pragma: no cover
    return "data"


class TestRelaxedMimeTypeValidation:
    """Test that MIME type validation accepts all RFC 2045 valid types."""

    def test_basic_mime_types(self):
        """Standard MIME types should be accepted."""
        for mime in [
            "text/plain",
            "application/json",
            "application/octet-stream",
            "image/png",
            "text/html",
            "text/csv",
            "application/xml",
        ]:
            r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
            assert r.mime_type == mime

    def test_mime_type_with_quoted_parameter_value(self):
        """Quoted parameter values are valid per RFC 2045 (the original issue)."""
        mime = 'text/plain; charset="utf-8"'
        r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
        assert r.mime_type == mime

    def test_mime_type_with_unquoted_parameter(self):
        """Unquoted parameter values should still work."""
        mime = "text/plain; charset=utf-8"
        r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
        assert r.mime_type == mime

    def test_mime_type_with_profile_parameter(self):
        """Profile parameter used by MCP-UI (from issue #1754)."""
        mime = "text/html;profile=mcp-app"
        r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
        assert r.mime_type == mime

    def test_mime_type_with_multiple_parameters(self):
        """Multiple parameters should be accepted."""
        mime = "text/plain; charset=utf-8; format=fixed"
        r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
        assert r.mime_type == mime

    def test_mime_type_with_vendor_type(self):
        """Vendor-specific MIME types (x- prefix, vnd.) should be accepted."""
        for mime in [
            "application/vnd.api+json",
            "application/x-www-form-urlencoded",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]:
            r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
            assert r.mime_type == mime

    def test_mime_type_with_suffix(self):
        """Structured syntax suffix types should be accepted."""
        for mime in [
            "application/ld+json",
            "application/soap+xml",
            "image/svg+xml",
        ]:
            r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
            assert r.mime_type == mime

    def test_mime_type_with_wildcard(self):
        """Wildcard MIME types should be accepted."""
        for mime in [
            "application/*",
            "*/*",
        ]:
            r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
            assert r.mime_type == mime

    def test_mime_type_with_complex_parameters(self):
        """Complex parameter values per RFC 2045."""
        for mime in [
            'multipart/form-data; boundary="----WebKitFormBoundary"',
            "text/html; charset=ISO-8859-1",
            'application/json; profile="https://example.com/schema"',
        ]:
            r = FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type=mime)
            assert r.mime_type == mime

    def test_invalid_mime_type_no_slash(self):
        """MIME types without '/' should be rejected."""
        with pytest.raises(ValueError, match="must contain a '/'"):
            FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type="plaintext")

    def test_invalid_mime_type_empty_string(self):
        """Empty string should be rejected (no '/')."""
        with pytest.raises(ValueError, match="must contain a '/'"):
            FunctionResource(uri="test://x", name="t", fn=_dummy, mime_type="")

    def test_default_mime_type(self):
        """Default MIME type should be text/plain."""
        r = FunctionResource(uri="test://x", name="t", fn=_dummy)
        assert r.mime_type == "text/plain"
