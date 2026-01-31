"""
DPoP (Demonstrating Proof-of-Possession) server-side verification.

RFC 9449: OAuth 2.0 Demonstrating Proof of Possession (DPoP).
Provides DPoPProofVerifier for validating DPoP proof JWTs and jti replay protection.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlparse, urlunparse

import jwt
from jwt import PyJWK

_SUPPORTED_ALGS = {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "PS256", "PS384", "PS512"}
_DEFAULT_IAT_WINDOW = 300  # seconds
DPOP_HEADER = "DPoP"


@dataclass
class DPoPProofInfo:
    """Validated DPoP proof information."""

    jti: str
    htm: str
    htu: str
    iat: int
    ath: str | None
    nonce: str | None
    jwk: dict[str, Any]
    jwk_thumbprint: str


class DPoPVerificationError(Exception):
    """DPoP verification failure with error code."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        self.message = message
        super().__init__(message)


class JTIReplayStore(Protocol):
    """Protocol for jti replay protection storage."""

    async def check_and_store(self, jti: str, exp_time: float) -> bool:
        """Check if jti is new (True) or replay (False), and store if new."""
        ...


class DPoPNonceStore(Protocol):
    """Protocol for server-managed DPoP nonce (optional feature)."""

    async def generate_nonce(self) -> str: ...
    async def validate_nonce(self, nonce: str) -> bool: ...


class InMemoryJTIReplayStore:
    """In-memory jti replay store. Not for distributed systems."""

    def __init__(self, max_size: int = 10000) -> None:
        self._store: dict[str, float] = {}
        self._max_size = max_size

    async def check_and_store(self, jti: str, exp_time: float) -> bool:
        now = time.time()
        if len(self._store) > self._max_size * 0.9:
            self._store = {k: v for k, v in self._store.items() if v > now}
        if jti in self._store:
            return False
        self._store[jti] = exp_time
        return True


class DPoPProofVerifier:
    """DPoP proof verifier per RFC 9449 Section 4.3."""

    def __init__(
        self,
        *,
        jti_store: JTIReplayStore | None = None,
        iat_window: int = _DEFAULT_IAT_WINDOW,
    ) -> None:
        self._jti_store = jti_store
        self._iat_window = iat_window

    async def verify(
        self,
        dpop_proof: str,
        http_method: str,
        http_uri: str,
        *,
        access_token: str | None = None,
        expected_jkt: str | None = None,
    ) -> DPoPProofInfo:
        """Verify DPoP proof per RFC 9449. Raises DPoPVerificationError on failure."""
        try:
            header = jwt.get_unverified_header(dpop_proof)
        except jwt.exceptions.DecodeError as e:
            raise DPoPVerificationError("invalid_dpop_proof", f"Malformed JWT: {e}") from e

        if header.get("typ") != "dpop+jwt":
            raise DPoPVerificationError("invalid_dpop_proof", "Invalid typ")
        alg = header.get("alg")
        if not alg or alg == "none" or alg not in _SUPPORTED_ALGS:
            raise DPoPVerificationError("invalid_dpop_proof", f"Invalid algorithm: {alg}")

        jwk_raw = header.get("jwk")
        if not jwk_raw or not isinstance(jwk_raw, dict):
            raise DPoPVerificationError("invalid_dpop_proof", "Missing or invalid jwk")
        jwk_dict = cast(dict[str, Any], jwk_raw)
        if any(k in jwk_dict for k in ("d", "p", "q", "dp", "dq", "qi", "k")):
            raise DPoPVerificationError("invalid_dpop_proof", "jwk contains private key")

        try:
            payload = jwt.decode(
                dpop_proof,
                key=PyJWK.from_dict(jwk_dict),
                algorithms=[alg],
                options={
                    "verify_signature": True,
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_iat": False,
                    "verify_aud": False,
                    "verify_iss": False,
                    "require": [],
                },
            )
        except jwt.exceptions.InvalidSignatureError as e:
            raise DPoPVerificationError("invalid_dpop_proof", "Signature failed") from e
        except jwt.exceptions.DecodeError as e:
            raise DPoPVerificationError("invalid_dpop_proof", f"Decode failed: {e}") from e

        for claim in ("jti", "htm", "htu", "iat"):
            if claim not in payload:
                raise DPoPVerificationError("invalid_dpop_proof", f"Missing {claim}")

        jti, htm, htu, iat = payload["jti"], payload["htm"], payload["htu"], payload["iat"]

        # Validate claim types to prevent AttributeError on malformed payloads
        if not isinstance(jti, str) or not jti:
            raise DPoPVerificationError("invalid_dpop_proof", "Invalid jti: must be non-empty string")
        if not isinstance(htm, str) or not htm:
            raise DPoPVerificationError("invalid_dpop_proof", "Invalid htm: must be non-empty string")
        if not isinstance(htu, str) or not htu:
            raise DPoPVerificationError("invalid_dpop_proof", "Invalid htu: must be non-empty string")

        if htm.upper() != http_method.upper():
            raise DPoPVerificationError("invalid_dpop_proof", "htm mismatch")
        if htu != _normalize_uri(http_uri):
            raise DPoPVerificationError("invalid_dpop_proof", "htu mismatch")

        now = time.time()
        if not isinstance(iat, int | float) or abs(now - iat) > self._iat_window:
            raise DPoPVerificationError("invalid_dpop_proof", "Invalid iat")
        if self._jti_store and not await self._jti_store.check_and_store(jti, now + self._iat_window):
            raise DPoPVerificationError("invalid_dpop_proof", "Replay detected")

        ath = payload.get("ath")
        if access_token and ath != _compute_ath(access_token):
            raise DPoPVerificationError("invalid_dpop_proof", "ath mismatch")

        thumbprint = _compute_thumbprint(jwk_dict)
        if expected_jkt and thumbprint != expected_jkt:
            raise DPoPVerificationError("invalid_dpop_proof", "jkt mismatch")

        return DPoPProofInfo(
            jti=jti,
            htm=htm,
            htu=htu,
            iat=int(iat),
            ath=ath,
            nonce=payload.get("nonce"),
            jwk=jwk_dict,
            jwk_thumbprint=thumbprint,
        )


def _normalize_uri(uri: str) -> str:
    p = urlparse(uri)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def _compute_ath(token: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(token.encode("ascii")).digest()).decode().rstrip("=")


def _compute_thumbprint(jwk: dict[str, Any]) -> str:
    kty = jwk.get("kty")
    if kty == "EC":
        canonical = {
            "crv": jwk["crv"], 
            "kty": "EC", 
            "x": jwk["x"], 
            "y": jwk["y"],
        }
    elif kty == "RSA":
        canonical = {
            "e": jwk["e"], 
            "kty": "RSA", 
            "n": jwk["n"],
        }
    else:
        raise DPoPVerificationError("invalid_dpop_proof", f"Unsupported kty: {kty}")
    return base64.urlsafe_b64encode(
        hashlib.sha256(json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()).digest()
    ).decode().rstrip("=")


def extract_dpop_proof(headers: dict[str, str]) -> str | None:
    """Extract DPoP proof from headers (case-insensitive)."""
    for k, v in headers.items():
        if k.lower() == "dpop":
            return v
    return None
