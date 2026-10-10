"""Tests for mcp.client.auth.dpop (RFC 9449 DPoP proofs)."""

import json

import jwt
import pytest
from jwt.algorithms import ECAlgorithm

from mcp.client.auth.dpop import (
    create_dpop_proof,
    dpop_public_jwk,
    dpop_thumbprint,
    generate_dpop_key,
    is_dpop_supported,
)
from mcp.shared.auth import ProtectedResourceMetadata

# RFC 9449, Figures 5/8/9: the example JWK and its published jkt.
RFC9449_EXAMPLE_JWK = {
    "kty": "EC",
    "crv": "P-256",
    "x": "l8tFrhx-34tV3hRICRDY9zCkDlpBhF42UQUfWVAWBFs",
    "y": "9VE4jf_Ok_o64zbTTlcuNJajHmt6v9TDVrU0CdvGRDA",
}
RFC9449_EXAMPLE_JKT = "0ZcOCORZNYy-DWpqq30jZyJGHTN0d2HglBV3uiguA4I"


def _decode_claims(proof: str) -> dict:
    """Claims without signature verification (structure assertions only)."""
    return jwt.decode(proof, options={"verify_signature": False})


def _verify_signature(proof: str) -> dict:
    """Full verification against the proof's embedded JWK."""
    header = jwt.get_unverified_header(proof)
    key = ECAlgorithm.from_jwk(json.dumps(header["jwk"]))
    return jwt.decode(proof, key, algorithms=["ES256"])


def test_dpop_proof_header_advertises_dpop_jwt_type():
    """RFC 9449 §4.2 mandates typ=dpop+jwt and alg=ES256 with an embedded JWK."""
    proof = create_dpop_proof(generate_dpop_key(), htm="POST", htu="https://a.example/token")
    header = jwt.get_unverified_header(proof)
    assert header["typ"] == "dpop+jwt"
    assert header["alg"] == "ES256"
    assert header["jwk"]["kty"] == "EC"
    assert "d" not in header["jwk"]


def test_dpop_proof_binds_method_and_uri_without_query_or_fragment():
    """RFC 9449 §4.2: htm/htu bind the request; htu carries no query/fragment."""
    proof = create_dpop_proof(generate_dpop_key(), htm="post", htu="https://a.example:8443/t/x?query=1#frag")
    claims = _decode_claims(proof)
    assert claims["htm"] == "POST"
    assert claims["htu"] == "https://a.example:8443/t/x"
    assert claims["iat"] > 0
    assert claims["jti"]


def test_dpop_proof_carries_server_nonce_only_when_challenged():
    """RFC 9449 §9.1: the nonce claim appears exactly when the server demanded one."""
    key = generate_dpop_key()
    assert _decode_claims(create_dpop_proof(key, htm="POST", htu="https://a.example/t")).get("nonce") is None
    assert (
        _decode_claims(create_dpop_proof(key, htm="POST", htu="https://a.example/t", nonce="srv-nonce"))["nonce"]
        == "srv-nonce"
    )


def test_dpop_proof_signature_verifies_with_embedded_key():
    """A proof minted by create_dpop_proof verifies against its embedded JWK."""
    proof = create_dpop_proof(generate_dpop_key(), htm="POST", htu="https://a.example/token")
    claims = _verify_signature(proof)
    assert claims["htm"] == "POST"
    assert claims["htu"] == "https://a.example/token"


def test_dpop_thumbprint_matches_rfc9449_published_value():
    """RFC 9449 Figures 8/9 publish the jkt of the Figure 5 example key."""
    assert dpop_thumbprint(RFC9449_EXAMPLE_JWK) == RFC9449_EXAMPLE_JKT


def test_dpop_proof_accepts_explicit_iat_and_jti():
    """Explicit iat/jti are honored instead of generated (deterministic tests)."""
    proof = create_dpop_proof(generate_dpop_key(), htm="GET", htu="https://a.example/r", iat=1234567890, jti="fixed-id")
    claims = _decode_claims(proof)
    assert claims["iat"] == 1234567890
    assert claims["jti"] == "fixed-id"


def test_dpop_public_jwk_never_carries_private_material():
    """The embedded JWK must not leak the private key."""
    public = dpop_public_jwk(generate_dpop_key())
    assert set(public) == {"kty", "crv", "x", "y"}


@pytest.mark.parametrize(
    ("algs", "expected"),
    [
        (None, False),
        ([], False),
        (["EdDSA"], False),
        (["ES256"], True),
        (["ES256", "EdDSA"], True),
    ],
)
def test_dpop_support_requires_es256_in_server_metadata(algs: list[str] | None, expected: bool):
    """DPoP activates only when the server advertises ES256 in its metadata."""
    metadata = (
        ProtectedResourceMetadata(
            resource="https://api.example.com/v1/mcp",
            authorization_servers=["https://auth.example.com"],
            dpop_signing_alg_values_supported=algs,
        )
        if algs is not None
        else None
    )
    assert is_dpop_supported(metadata) is expected


def test_dpop_support_ignores_metadata_without_dpop_field():
    """Servers that predate DPoP metadata simply don't get proofs."""
    metadata = ProtectedResourceMetadata(
        resource="https://api.example.com/v1/mcp",
        authorization_servers=["https://auth.example.com"],
    )
    assert is_dpop_supported(metadata) is False
