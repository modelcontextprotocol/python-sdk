"""Standard Webhooks signing, the scheme SEP-3415 webhook deliveries use.

See https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

__all__ = ["decode_secret", "sign", "verify"]

_PREFIX = "whsec_"


def decode_secret(secret: str) -> bytes:
    """Return the key bytes of a `whsec_` secret.

    Raises:
        ValueError: The secret is not `whsec_` plus base64 of 24 to 64 bytes.
    """
    if not secret.startswith(_PREFIX):
        raise ValueError("secret must start with 'whsec_'")
    try:
        key = base64.b64decode(secret.removeprefix(_PREFIX), validate=True)
    except binascii.Error:
        raise ValueError("secret must be 'whsec_' followed by base64") from None
    if not 24 <= len(key) <= 64:
        raise ValueError("secret must encode 24 to 64 bytes")
    return key


def sign(secret: str, message_id: str, timestamp: int, body: bytes) -> str:
    """Return the base64 `v1` signature of one message made with `secret`."""
    signed = f"{message_id}.{timestamp}.".encode() + body
    digest = hmac.new(decode_secret(secret), signed, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify(secret: str, message_id: str, timestamp: int, body: bytes, signature_header: str) -> bool:
    """Whether any `v1,` signature in a `webhook-signature` header was made with `secret` over exactly these bytes."""
    expected = sign(secret, message_id, timestamp, body)
    return any(
        hmac.compare_digest(candidate.removeprefix("v1,"), expected)
        for candidate in signature_header.split()
        if candidate.startswith("v1,")
    )
