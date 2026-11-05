"""The outbound side of webhook delivery: signed POSTs to client-supplied callback URLs.

Callback URLs come from clients, so every POST goes through the SSRF rules of SEP-3415:
`https` only, the host resolved at send time and refused unless every address is
public, the connection made to the address that was checked (with the original
`Host` and TLS SNI), and redirects never followed.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import ssl
import time
from collections.abc import Collection, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx2

from mcp.experimental.events.signing import sign
from mcp.experimental.events.types import DeliveryError


class CallbackFailure(Exception):
    """An attempt to reach a callback URL failed, for the reported reason."""

    def __init__(self, reason: DeliveryError) -> None:
        super().__init__(reason)
        self.reason: DeliveryError = reason


class NonPublicAddress(ValueError):
    """A callback URL resolved to an address that is not globally routable."""


class Callbacks:
    def __init__(self, client: httpx2.AsyncClient, trusted_origins: Collection[str]) -> None:
        self._client = client
        self._trusted = {origin.rstrip("/").lower() for origin in trusted_origins}

    def validate(self, url: str) -> None:
        """Raises `ValueError` unless `url` is an absolute `https` URL or under a trusted origin."""
        parts = urlsplit(url)
        if not parts.hostname:
            raise ValueError("delivery.url must be an absolute URL")
        if parts.scheme != "https" and not self._is_trusted(url):
            raise ValueError("delivery.url must use https")

    async def post(
        self, url: str, subscription_id: str, secrets: Sequence[str], message_id: str, body: dict[str, Any]
    ) -> httpx2.Response:
        """Sign and POST `body` once.

        Raises:
            NonPublicAddress: The host resolved to a non-public address.
            CallbackFailure: The endpoint could not be reached.
        """
        content = json.dumps(body, separators=(",", ":")).encode()
        timestamp = int(time.time())
        headers = {
            "content-type": "application/json",
            "webhook-id": message_id,
            "webhook-timestamp": str(timestamp),
            "webhook-signature": " ".join(f"v1,{sign(secret, message_id, timestamp, content)}" for secret in secrets),
            "x-mcp-subscription-id": subscription_id,
        }
        extensions: dict[str, Any] = {}
        if not self._is_trusted(url):
            parts = urlsplit(url)
            address = await _public_address(parts.hostname or "", parts.port or 443)
            host = f"[{address}]" if ":" in address else address
            url = urlunsplit(parts._replace(netloc=f"{host}:{parts.port or 443}"))
            headers["host"] = parts.netloc
            extensions["sni_hostname"] = parts.hostname
        try:
            return await self._client.post(
                url, content=content, headers=headers, extensions=extensions, follow_redirects=False
            )
        except httpx2.TimeoutException:
            raise CallbackFailure("timeout") from None
        except httpx2.TransportError as exc:
            raise CallbackFailure("tls_error" if _caused_by_tls(exc) else "connection_refused") from None

    async def verify(self, url: str, subscription_id: str, secret: str) -> None:
        """Prove the endpoint wants deliveries: it must echo a fresh challenge in a 2xx body.

        Raises:
            NonPublicAddress: The host resolved to a non-public address.
            CallbackFailure: The endpoint was unreachable or did not echo the challenge.
        """
        challenge = secrets.token_urlsafe(32)
        message_id = f"msg_verification_{secrets.token_hex(12)}"
        response = await self.post(
            url, subscription_id, [secret], message_id, {"type": "verification", "challenge": challenge}
        )
        if not response.is_success:
            raise CallbackFailure("http_5xx" if response.status_code >= 500 else "http_4xx")
        try:
            echoed = response.json().get("challenge")
        except (ValueError, AttributeError):
            echoed = None
        if not isinstance(echoed, str) or not hmac.compare_digest(echoed, challenge):
            raise CallbackFailure("challenge_failed")

    def _is_trusted(self, url: str) -> bool:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}".lower() in self._trusted


async def _public_address(host: str, port: int) -> str:
    try:
        infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise CallbackFailure("connection_refused") from None
    addresses = [str(info[4][0]) for info in infos]
    if not all(ipaddress.ip_address(address).is_global for address in addresses):
        raise NonPublicAddress(f"{host} resolves to a non-public address")
    return addresses[0]


def _caused_by_tls(exc: BaseException) -> bool:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return True
        cause = cause.__cause__ or cause.__context__
    return False
