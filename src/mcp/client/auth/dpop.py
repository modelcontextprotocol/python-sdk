"""
DPoP (Demonstrating Proof-of-Possession) client implementation.

RFC 9449: OAuth 2.0 Demonstrating Proof of Possession (DPoP).
Provides DPoPKeyPair, DPoPProofGenerator, DPoPStorage for generating DPoP proof JWTs.
"""

import base64
import hashlib
import secrets
import time
from typing import Any, Literal

import jwt
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from mcp.client.auth.protocol import DPoPProofGenerator, DPoPStorage

DPoPAlgorithm = Literal["ES256", "RS256"]

_BITS_PER_BYTE = 8
# NIST SP 800-57 recommended minimum for RSA keys (valid through 2030+)
RSA_KEY_SIZE_DEFAULT = 2048
# RFC 8017 / cryptography library recommended value
_RSA_PUBLIC_EXPONENT = 65537


def _int_to_base64url(num: int) -> str:
    """Encode integer to base64url without padding."""
    size = (num.bit_length() + _BITS_PER_BYTE - 1) // _BITS_PER_BYTE
    data = num.to_bytes(size, "big")
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


class DPoPKeyPair:
    """DPoP key pair holding private key and public JWK."""

    def __init__(
        self,
        private_key: EllipticCurvePrivateKey | RSAPrivateKey,
        algorithm: DPoPAlgorithm = "ES256",
    ) -> None:
        self._private_key: EllipticCurvePrivateKey | RSAPrivateKey = private_key
        self._algorithm = algorithm
        self._public_jwk = _key_to_jwk(private_key)

    @property
    def algorithm(self) -> str:
        return self._algorithm

    @property
    def public_key_jwk(self) -> dict[str, Any]:
        return self._public_jwk.copy()

    @classmethod
    def generate(
        cls,
        algorithm: DPoPAlgorithm = "ES256",
        *,
        rsa_key_size: int = RSA_KEY_SIZE_DEFAULT,
    ) -> "DPoPKeyPair":
        """Generate a new DPoP key pair.

        Args:
            algorithm: Signing algorithm, "ES256" (default) or "RS256".
            rsa_key_size: RSA key size in bits (default 2048, minimum 2048).
                Only used when algorithm is "RS256".

        Raises:
            ValueError: If algorithm is unsupported or rsa_key_size < 2048.
        """
        from cryptography.hazmat.primitives.asymmetric.ec import (
            SECP256R1,
        )
        from cryptography.hazmat.primitives.asymmetric.ec import (
            generate_private_key as ec_generate,
        )
        from cryptography.hazmat.primitives.asymmetric.rsa import (
            generate_private_key as rsa_generate,
        )

        if algorithm == "ES256":
            key: EllipticCurvePrivateKey | RSAPrivateKey = ec_generate(SECP256R1())
        elif algorithm == "RS256":
            if rsa_key_size < RSA_KEY_SIZE_DEFAULT:
                raise ValueError(
                    f"RSA key size must be at least {RSA_KEY_SIZE_DEFAULT} bits, got {rsa_key_size}"
                )
            key = rsa_generate(public_exponent=_RSA_PUBLIC_EXPONENT, key_size=rsa_key_size)
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        return cls(key, algorithm)

    def sign_dpop_jwt(self, payload: dict[str, Any], headers: dict[str, Any]) -> str:
        """Sign a DPoP JWT with the private key."""
        return jwt.encode(
            payload,
            self._private_key,
            algorithm=self._algorithm,
            headers=headers,
        )


def _key_to_jwk(key: EllipticCurvePrivateKey | RSAPrivateKey) -> dict[str, Any]:
    """Convert a private key to public JWK (no private components)."""
    if isinstance(key, EllipticCurvePrivateKey):
        pub = key.public_key()
        nums = pub.public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": _int_to_base64url(nums.x),
            "y": _int_to_base64url(nums.y),
        }
    # key is RSAPrivateKey (union type)
    pub = key.public_key()
    nums = pub.public_numbers()
    return {
        "kty": "RSA",
        "n": _int_to_base64url(nums.n),
        "e": _int_to_base64url(nums.e),
    }


class DPoPProofGeneratorImpl(DPoPProofGenerator):
    """DPoP proof generator implementing the DPoPProofGenerator protocol."""

    def __init__(self, key_pair: DPoPKeyPair) -> None:
        self._key_pair = key_pair

    def generate_proof(
        self,
        method: str,
        uri: str,
        credential: str | None = None,
        nonce: str | None = None,
    ) -> str:
        """Generate a DPoP proof JWT per RFC 9449."""
        htu = _normalize_htu(uri)
        payload: dict[str, Any] = {
            "jti": secrets.token_urlsafe(32),
            "htm": method.upper(),
            "htu": htu,
            "iat": int(time.time()),
        }
        if credential:
            payload["ath"] = _ath_hash(credential)
        if nonce:
            payload["nonce"] = nonce

        headers: dict[str, Any] = {
            "typ": "dpop+jwt",
            "alg": self._key_pair.algorithm,
            "jwk": self._key_pair.public_key_jwk,
        }

        return self._key_pair.sign_dpop_jwt(payload, headers)

    def get_public_key_jwk(self) -> dict[str, Any]:
        return self._key_pair.public_key_jwk


def _normalize_htu(uri: str) -> str:
    """Strip query and fragment from URI per RFC 9449 htu claim."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(uri)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _ath_hash(access_token: str) -> str:
    """Base64url-encoded SHA-256 hash of ASCII access token."""
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def compute_jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """Compute JWK Thumbprint (RFC 7638) for cnf.jkt binding."""
    import json

    kty = jwk.get("kty")
    if kty == "EC":
        canonical = {"crv": jwk["crv"], "kty": "EC", "x": jwk["x"], "y": jwk["y"]}
    elif kty == "RSA":
        canonical = {"e": jwk["e"], "kty": "RSA", "n": jwk["n"]}
    else:
        raise ValueError(f"Unsupported key type: {kty}")
    data = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


class InMemoryDPoPStorage(DPoPStorage):
    """In-memory DPoP key pair storage.

    Note: Not thread-safe. Suitable for single-threaded or async environments.
    """

    def __init__(self) -> None:
        self._store: dict[str, DPoPKeyPair] = {}

    async def get_key_pair(self, protocol_id: str) -> DPoPKeyPair | None:
        return self._store.get(protocol_id)

    async def set_key_pair(self, protocol_id: str, key_pair: DPoPKeyPair) -> None:
        self._store[protocol_id] = key_pair
