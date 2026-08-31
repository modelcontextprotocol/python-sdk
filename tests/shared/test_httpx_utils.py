"""Tests for httpx2 client factory and its SSRF redirect protection."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx2
import pytest

from mcp.shared._httpx_utils import (
    RedirectPolicy,
    _is_internal_or_non_global,
    create_mcp_http_client,
)


def test_default_settings():
    """Test that default settings are applied correctly."""
    client = create_mcp_http_client()

    assert client.follow_redirects is True
    assert client.timeout.connect == 30.0


def test_custom_parameters():
    """Test custom headers and timeout are set correctly."""
    headers = {"Authorization": "Bearer token"}
    timeout = httpx2.Timeout(60.0)

    client = create_mcp_http_client(headers, timeout)

    assert client.headers["Authorization"] == "Bearer token"
    assert client.timeout.connect == 60.0


def test_redirect_policy_none_disables_follow():
    """NONE must set follow_redirects=False and install no guard."""
    client = create_mcp_http_client(redirect_policy=RedirectPolicy.NONE)
    assert client.follow_redirects is False
    assert not client._event_hooks["request"]


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("sub.localhost", True),
        ("10.0.0.5", True),
        ("172.16.1.1", True),
        ("172.31.255.255", True),
        ("192.168.1.10", True),
        ("169.254.169.254", True),  # cloud metadata endpoint
        ("::1", True),
        ("fc00::1", True),
        ("fe80::1", True),
        ("0.0.0.0", True),
        # Public / non-literal hosts must be treated as external
        ("93.184.216.34", False),
        ("example.com", False),
        ("1.2.3.4", False),
    ],
)
def test_is_internal_or_non_global(host, expected):
    assert _is_internal_or_non_global(host) is expected


# ---------------------------------------------------------------------------
# Redirect guard integration: a live local server that bounces HTTP to a target.
# ---------------------------------------------------------------------------


class _RedirectServerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    redirect_status = 307
    target = None  # set per-server

    def log_message(self, *args):  # keep test output clean
        pass

    def do_GET(self):
        if not self.target or self.path != "/":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(self.redirect_status)
        self.send_header("Location", self.target)
        self.send_header("Content-Length", "0")
        self.end_headers()


class _TargetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b"internal-reply"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Server:
    def __init__(self, handler):
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self):
        return self._httpd.server_address[1]

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture(scope="module")
def servers():
    target = _Server(_TargetHandler)
    redirector = _Server(_RedirectServerHandler)
    yield redirector, target
    redirector.close()
    target.close()


def _get(client: httpx2.AsyncClient, url: str) -> httpx2.Response:
    return asyncio.run(client.get(url))


def test_safe_policy_blocks_redirect_to_internal(servers):
    """Default SAFE policy must refuse to follow a redirect into loopback."""
    redirector, target = servers
    _RedirectServerHandler.target = f"http://127.0.0.1:{target.port}/injected"
    client = create_mcp_http_client()  # default = SAFE
    with pytest.raises(httpx2.ConnectError, match="internal/private host"):
        _get(client, f"http://127.0.0.1:{redirector.port}/")


def test_all_policy_follows_redirect_to_internal(servers):
    """Explicit ALL keeps legacy behavior: redirect into loopback is followed."""
    redirector, target = servers
    _RedirectServerHandler.target = f"http://127.0.0.1:{target.port}/injected"
    client = create_mcp_http_client(redirect_policy=RedirectPolicy.ALL)
    resp = _get(client, f"http://127.0.0.1:{redirector.port}/")
    assert resp.status_code == 200
    assert resp.text == "internal-reply"


def test_same_host_policy_still_follows_same_host_redirect(servers):
    """SAME_HOST must not block the common same-host bounce."""
    redirector, _ = servers
    _RedirectServerHandler.target = f"http://127.0.0.1:{redirector.port}/noop"
    client = create_mcp_http_client(redirect_policy=RedirectPolicy.SAME_HOST)
    resp = _get(client, f"http://127.0.0.1:{redirector.port}/")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_none_policy_does_not_follow_redirect(servers):
    """NONE must return the 3xx without following, so no rebinding occurs."""
    redirector, _ = servers
    _RedirectServerHandler.target = "http://127.0.0.1:9999/nope"
    client = create_mcp_http_client(redirect_policy=RedirectPolicy.NONE)
    resp = _get(client, f"http://127.0.0.1:{redirector.port}/")
    assert resp.status_code == 307
