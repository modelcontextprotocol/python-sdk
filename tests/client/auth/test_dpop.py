"""Unit tests for DPoP client (DPoPKeyPair, DPoPProofGenerator, DPoPStorage)."""

import base64
import hashlib

import jwt
import pytest

from mcp.client.auth.dpop import (
    DPoPKeyPair,
    DPoPProofGeneratorImpl,
    InMemoryDPoPStorage,
    compute_jwk_thumbprint,
)


def test_dpop_key_pair_generate_es256() -> None:
    pair = DPoPKeyPair.generate("ES256")
    assert pair.algorithm == "ES256"
    jwk = pair.public_key_jwk
    assert jwk["kty"] == "EC"
    assert jwk["crv"] == "P-256"
    assert "x" in jwk and "y" in jwk


def test_dpop_key_pair_generate_rs256() -> None:
    pair = DPoPKeyPair.generate("RS256")
    assert pair.algorithm == "RS256"
    jwk = pair.public_key_jwk
    assert jwk["kty"] == "RSA"
    assert "n" in jwk and "e" in jwk


def test_dpop_proof_generator_produces_valid_jwt() -> None:
    pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(pair)
    proof = gen.generate_proof("POST", "https://example.com/token")
    decoded = jwt.decode(proof, options={"verify_signature": False})
    assert decoded["htm"] == "POST"
    assert decoded["htu"] == "https://example.com/token"
    assert "jti" in decoded and "iat" in decoded


def test_dpop_proof_includes_ath_when_credential_provided() -> None:
    pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(pair)
    proof = gen.generate_proof("GET", "https://rs.example/res", credential="my-token")
    decoded = jwt.decode(proof, options={"verify_signature": False})
    expected_ath = base64.urlsafe_b64encode(
        hashlib.sha256(b"my-token").digest()
    ).decode().rstrip("=")
    assert decoded["ath"] == expected_ath


def test_dpop_proof_includes_nonce_when_provided() -> None:
    pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(pair)
    proof = gen.generate_proof("POST", "https://as.example/token", nonce="server-nonce")
    decoded = jwt.decode(proof, options={"verify_signature": False})
    assert decoded["nonce"] == "server-nonce"


def test_dpop_proof_htu_strips_query_and_fragment() -> None:
    pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(pair)
    proof = gen.generate_proof("GET", "https://example.com/path?q=1#frag")
    decoded = jwt.decode(proof, options={"verify_signature": False})
    assert decoded["htu"] == "https://example.com/path"


def test_dpop_proof_signature_verifiable() -> None:
    pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(pair)
    proof = gen.generate_proof("POST", "https://example.com/token")
    header = jwt.get_unverified_header(proof)
    assert header["typ"] == "dpop+jwt"
    assert header["alg"] == "ES256"
    assert "jwk" in header


@pytest.mark.anyio
async def test_in_memory_dpop_storage() -> None:
    storage = InMemoryDPoPStorage()
    pair = DPoPKeyPair.generate("ES256")
    assert await storage.get_key_pair("oauth2") is None
    await storage.set_key_pair("oauth2", pair)
    retrieved = await storage.get_key_pair("oauth2")
    assert retrieved is not None
    assert retrieved.public_key_jwk == pair.public_key_jwk


def test_compute_jwk_thumbprint_ec() -> None:
    pair = DPoPKeyPair.generate("ES256")
    jwk = pair.public_key_jwk
    thumbprint = compute_jwk_thumbprint(jwk)
    # Thumbprint should be base64url-encoded SHA-256 (43 chars without padding)
    assert len(thumbprint) == 43
    assert "=" not in thumbprint


def test_compute_jwk_thumbprint_rsa() -> None:
    pair = DPoPKeyPair.generate("RS256")
    jwk = pair.public_key_jwk
    thumbprint = compute_jwk_thumbprint(jwk)
    assert len(thumbprint) == 43
    assert "=" not in thumbprint


def test_dpop_key_pair_generate_rs256_custom_key_size() -> None:
    pair = DPoPKeyPair.generate("RS256", rsa_key_size=4096)
    assert pair.algorithm == "RS256"
    jwk = pair.public_key_jwk
    assert jwk["kty"] == "RSA"
    # 4096-bit key has larger modulus than 2048-bit
    # base64url of 4096-bit n is ~683 chars vs ~342 for 2048-bit
    assert len(jwk["n"]) > 400


def test_dpop_key_pair_generate_rs256_rejects_small_key_size() -> None:
    with pytest.raises(ValueError, match="RSA key size must be at least 2048"):
        DPoPKeyPair.generate("RS256", rsa_key_size=1024)
