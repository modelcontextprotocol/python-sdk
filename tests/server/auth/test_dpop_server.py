"""Unit tests for DPoP server-side verification."""

import time

import pytest

from mcp.client.auth.dpop import DPoPKeyPair, DPoPProofGeneratorImpl, compute_jwk_thumbprint
from mcp.server.auth.dpop import (
    DPoPProofInfo,
    DPoPProofVerifier,
    DPoPVerificationError,
    InMemoryJTIReplayStore,
    extract_dpop_proof,
)


@pytest.fixture
def verifier() -> DPoPProofVerifier:
    return DPoPProofVerifier()


@pytest.fixture
def key_pair() -> DPoPKeyPair:
    return DPoPKeyPair.generate("ES256")


@pytest.fixture
def gen(key_pair: DPoPKeyPair) -> DPoPProofGeneratorImpl:
    return DPoPProofGeneratorImpl(key_pair)


@pytest.mark.anyio
async def test_verify_valid_proof(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("POST", "https://server.example.com/token")
    result = await verifier.verify(proof, "POST", "https://server.example.com/token")
    assert isinstance(result, DPoPProofInfo)
    assert result.htm == "POST" and result.htu == "https://server.example.com/token"


@pytest.mark.anyio
async def test_verify_with_access_token(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("GET", "https://api.example.com/res", credential="test-token")
    result = await verifier.verify(proof, "GET", "https://api.example.com/res", access_token="test-token")
    assert result.ath is not None


@pytest.mark.anyio
async def test_verify_with_expected_jkt(
    verifier: DPoPProofVerifier, key_pair: DPoPKeyPair, gen: DPoPProofGeneratorImpl
) -> None:
    proof = gen.generate_proof("POST", "https://server.example.com/token")
    jkt = compute_jwk_thumbprint(key_pair.public_key_jwk)
    result = await verifier.verify(proof, "POST", "https://server.example.com/token", expected_jkt=jkt)
    assert result.jwk_thumbprint == jkt


@pytest.mark.anyio
async def test_rejects_htm_mismatch(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("POST", "https://server.example.com/token")
    with pytest.raises(DPoPVerificationError) as exc:
        await verifier.verify(proof, "GET", "https://server.example.com/token")
    assert exc.value.error_code == "invalid_dpop_proof"


@pytest.mark.anyio
async def test_rejects_htu_mismatch(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("POST", "https://server.example.com/token")
    with pytest.raises(DPoPVerificationError) as exc:
        await verifier.verify(proof, "POST", "https://other.example.com/token")
    assert exc.value.error_code == "invalid_dpop_proof"


@pytest.mark.anyio
async def test_accepts_uri_with_query(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("GET", "https://api.example.com/resource")
    result = await verifier.verify(proof, "GET", "https://api.example.com/resource?foo=bar#frag")
    assert result.htu == "https://api.example.com/resource"


@pytest.mark.anyio
async def test_rejects_ath_mismatch(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("GET", "https://api.example.com/res", credential="token-a")
    with pytest.raises(DPoPVerificationError) as exc:
        await verifier.verify(proof, "GET", "https://api.example.com/res", access_token="token-b")
    assert "ath mismatch" in exc.value.message


@pytest.mark.anyio
async def test_rejects_jkt_mismatch(verifier: DPoPProofVerifier, gen: DPoPProofGeneratorImpl) -> None:
    proof = gen.generate_proof("POST", "https://server.example.com/token")
    with pytest.raises(DPoPVerificationError) as exc:
        await verifier.verify(proof, "POST", "https://server.example.com/token", expected_jkt="wrong")
    assert "jkt mismatch" in exc.value.message


@pytest.mark.anyio
async def test_verify_rs256() -> None:
    verifier = DPoPProofVerifier()
    kp = DPoPKeyPair.generate("RS256")
    proof = DPoPProofGeneratorImpl(kp).generate_proof("POST", "https://server.example.com/token")
    result = await verifier.verify(proof, "POST", "https://server.example.com/token")
    assert result.jwk["kty"] == "RSA"


def test_extract_dpop_proof_case_insensitive() -> None:
    assert extract_dpop_proof({"DPoP": "p1"}) == "p1"
    assert extract_dpop_proof({"dpop": "p2"}) == "p2"
    assert extract_dpop_proof({"Authorization": "Bearer x"}) is None


@pytest.mark.anyio
async def test_jti_store_detects_replay() -> None:
    store = InMemoryJTIReplayStore()
    exp = time.time() + 300
    assert await store.check_and_store("jti-1", exp) is True
    assert await store.check_and_store("jti-1", exp) is False
    assert await store.check_and_store("jti-2", exp) is True


@pytest.mark.anyio
async def test_verifier_with_jti_store_rejects_replay(gen: DPoPProofGeneratorImpl) -> None:
    store = InMemoryJTIReplayStore()
    verifier = DPoPProofVerifier(jti_store=store)
    proof = gen.generate_proof("POST", "https://server.example.com/token")
    await verifier.verify(proof, "POST", "https://server.example.com/token")
    with pytest.raises(DPoPVerificationError) as exc:
        await verifier.verify(proof, "POST", "https://server.example.com/token")
    assert "Replay" in exc.value.message


@pytest.mark.anyio
async def test_rejects_invalid_claim_types(verifier: DPoPProofVerifier, key_pair: DPoPKeyPair) -> None:
    """Verify that non-string claim types are rejected with DPoPVerificationError."""
    import jwt as pyjwt

    # Create a proof with invalid htm type (integer instead of string)
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": key_pair.public_key_jwk}
    payload = {
        "jti": "test-jti",
        "htm": 123,  # Invalid: should be string
        "htu": "https://example.com/token",
        "iat": int(time.time()),
    }
    invalid_proof = pyjwt.encode(payload, key_pair._private_key, algorithm="ES256", headers=header)

    with pytest.raises(DPoPVerificationError) as exc:
        await verifier.verify(invalid_proof, "POST", "https://example.com/token")
    assert "Invalid htm" in exc.value.message
