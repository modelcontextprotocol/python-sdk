"""DPoP (RFC 9449) proofs for token endpoint requests.

Attached when the authorization server advertises
``dpop_signing_alg_values_supported`` in its metadata. Binds issued tokens to
the client's key so stolen codes or refresh tokens cannot be redeemed
elsewhere. Token endpoint only; resource-server proofs (RFC 9449 §7) are
future work. Implemented on ``pyjwt[crypto]`` — no new dependencies.
"""

import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlsplit, urlunsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

from mcp.shared.auth import ProtectedResourceMetadata


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _private_key(private_jwk_json: str) -> ec.EllipticCurvePrivateKey:
    jwk = json.loads(private_jwk_json)
    return ec.derive_private_key(int.from_bytes(_b64u_decode(jwk["d"]), "big"), ec.SECP256R1())


def _normalize_htu(htu: str) -> str:
    """RFC 9449 §4.2: the ``htu`` claim carries no query or fragment."""
    parts = urlsplit(htu)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def generate_dpop_key() -> str:
    """Generate a fresh P-256 keypair; returns the private JWK as JSON."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.private_numbers()
    public = numbers.public_numbers
    return json.dumps(
        {
            "kty": "EC",
            "crv": "P-256",
            "x": _b64u(public.x.to_bytes(32, "big")),
            "y": _b64u(public.y.to_bytes(32, "big")),
            "d": _b64u(numbers.private_value.to_bytes(32, "big")),
        }
    )


def dpop_public_jwk(private_jwk_json: str) -> dict[str, str]:
    """Public JWK (no private material) from a private JWK JSON string."""
    jwk = json.loads(private_jwk_json)
    return {k: jwk[k] for k in ("kty", "crv", "x", "y")}


def dpop_thumbprint(public_jwk: dict[str, str]) -> str:
    """RFC 7638 JWK SHA-256 thumbprint (the ``jkt`` key identifier)."""
    required = {k: public_jwk[k] for k in ("crv", "kty", "x", "y")}
    canonical = json.dumps(required, separators=(",", ":"), sort_keys=True)
    return _b64u(hashlib.sha256(canonical.encode("utf-8")).digest())


def create_dpop_proof(
    private_jwk_json: str,
    *,
    htm: str,
    htu: str,
    nonce: str | None = None,
    iat: int | None = None,
    jti: str | None = None,
) -> str:
    """Create a DPoP proof JWT for one HTTP request (RFC 9449 §4)."""
    public_jwk = dpop_public_jwk(private_jwk_json)
    payload: dict[str, object] = {
        "jti": jti or secrets.token_urlsafe(32),
        "htm": htm.upper(),
        "htu": _normalize_htu(htu),
        "iat": iat if iat is not None else int(time.time()),
    }
    if nonce is not None:
        payload["nonce"] = nonce
    return jwt.encode(
        payload,
        _private_key(private_jwk_json),
        algorithm="ES256",
        headers={"typ": "dpop+jwt", "jwk": public_jwk},
    )


def is_dpop_supported(resource_metadata: ProtectedResourceMetadata | None) -> bool:
    """Whether the server advertises ES256 DPoP support.

    The SDK surfaces ``dpop_signing_alg_values_supported`` on the protected
    resource metadata (RFC 9728 discovery document).
    """
    algs = getattr(resource_metadata, "dpop_signing_alg_values_supported", None)
    return bool(algs) and "ES256" in algs
