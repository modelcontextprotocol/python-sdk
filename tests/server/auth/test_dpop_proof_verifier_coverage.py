"""Coverage tests for server-side DPoPProofVerifier."""

from __future__ import annotations

from typing import Any, cast

import jwt
import pytest

from mcp.client.auth.dpop import DPoPKeyPair, DPoPProofGeneratorImpl
from mcp.server.auth.dpop import (
    DPoPNonceStore,
    DPoPProofVerifier,
    DPoPVerificationError,
    InMemoryJTIReplayStore,
    _compute_thumbprint,
)


@pytest.mark.anyio
async def test_dpop_nonce_store_protocol_stubs_are_executable_for_branch_coverage() -> None:
    generate_nonce = cast(Any, DPoPNonceStore.generate_nonce)
    assert await generate_nonce(object()) is None
    validate_nonce = cast(Any, DPoPNonceStore.validate_nonce)
    assert await validate_nonce(object(), "n") is None


@pytest.mark.anyio
async def test_in_memory_jti_store_prunes_when_near_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mcp.server.auth.dpop.time.time", lambda: 100.0)

    store = InMemoryJTIReplayStore(max_size=10)
    for i in range(10):
        store._store[f"old-{i}"] = 0.0  # expired

    ok = await store.check_and_store("new", exp_time=200.0)
    assert ok is True
    assert "new" in store._store
    assert all(k == "new" or v > 100.0 for k, v in store._store.items())


def test_compute_thumbprint_rejects_unsupported_kty() -> None:
    with pytest.raises(DPoPVerificationError, match="Unsupported kty"):
        _compute_thumbprint({"kty": "oct"})


@pytest.mark.anyio
async def test_verify_rejects_malformed_jwt() -> None:
    verifier = DPoPProofVerifier()
    with pytest.raises(DPoPVerificationError, match="Malformed JWT"):
        await verifier.verify("not-a-jwt", "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_invalid_typ() -> None:
    key_pair = DPoPKeyPair.generate("ES256")
    proof = key_pair.sign_dpop_jwt(
        payload={"jti": "j", "htm": "GET", "htu": "https://example.com/x", "iat": 1},
        headers={"typ": "JWT", "alg": "ES256", "jwk": key_pair.public_key_jwk},
    )
    verifier = DPoPProofVerifier()
    with pytest.raises(DPoPVerificationError, match="Invalid typ"):
        await verifier.verify(proof, "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_unsupported_algorithm() -> None:
    token = jwt.encode(
        {"jti": "j", "htm": "GET", "htu": "https://example.com/x", "iat": 1},
        "secret",
        algorithm="HS256",
        headers={"typ": "dpop+jwt", "jwk": {"kty": "EC", "crv": "P-256", "x": "x", "y": "y"}},
    )
    verifier = DPoPProofVerifier()
    with pytest.raises(DPoPVerificationError, match="Invalid algorithm"):
        await verifier.verify(token, "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_missing_or_private_jwk() -> None:
    key_pair = DPoPKeyPair.generate("ES256")
    payload = {"jti": "j", "htm": "GET", "htu": "https://example.com/x", "iat": 1}

    missing_jwk = key_pair.sign_dpop_jwt(payload, headers={"typ": "dpop+jwt", "alg": "ES256"})
    verifier = DPoPProofVerifier()
    with pytest.raises(DPoPVerificationError, match="Missing or invalid jwk"):
        await verifier.verify(missing_jwk, "GET", "https://example.com/x")

    private_jwk = key_pair.sign_dpop_jwt(
        payload,
        headers={
            "typ": "dpop+jwt",
            "alg": "ES256",
            "jwk": {**key_pair.public_key_jwk, "d": "private"},
        },
    )
    with pytest.raises(DPoPVerificationError, match="private key"):
        await verifier.verify(private_jwk, "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_invalid_signature_and_decode_fail() -> None:
    key_pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(key_pair)
    proof = gen.generate_proof("GET", "https://example.com/x")

    verifier = DPoPProofVerifier()
    parts = proof.split(".")
    tampered = ".".join([parts[0], parts[1], parts[2][::-1]])
    with pytest.raises(DPoPVerificationError, match="Signature failed"):
        await verifier.verify(tampered, "GET", "https://example.com/x")

    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
    from jwt.api_jws import PyJWS

    private_key = generate_private_key(SECP256R1())
    pair_for_decode_error = DPoPKeyPair(private_key, "ES256")
    bad_payload = PyJWS().encode(
        payload=b"not-json",
        key=private_key,
        algorithm="ES256",
        headers={"typ": "dpop+jwt", "alg": "ES256", "jwk": pair_for_decode_error.public_key_jwk},
    )
    with pytest.raises(DPoPVerificationError, match="Decode failed"):
        await verifier.verify(bad_payload, "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_missing_claims_and_invalid_claim_types() -> None:
    key_pair = DPoPKeyPair.generate("ES256")
    verifier = DPoPProofVerifier()

    missing_jti = key_pair.sign_dpop_jwt(
        payload={"htm": "GET", "htu": "https://example.com/x", "iat": 1},
        headers={"typ": "dpop+jwt", "alg": "ES256", "jwk": key_pair.public_key_jwk},
    )
    with pytest.raises(DPoPVerificationError, match="Missing jti"):
        await verifier.verify(missing_jti, "GET", "https://example.com/x")

    bad_jti = key_pair.sign_dpop_jwt(
        payload={"jti": "", "htm": "GET", "htu": "https://example.com/x", "iat": 1},
        headers={"typ": "dpop+jwt", "alg": "ES256", "jwk": key_pair.public_key_jwk},
    )
    with pytest.raises(DPoPVerificationError, match="Invalid jti"):
        await verifier.verify(bad_jti, "GET", "https://example.com/x")

    bad_htu = key_pair.sign_dpop_jwt(
        payload={"jti": "j", "htm": "GET", "htu": "", "iat": 1},
        headers={"typ": "dpop+jwt", "alg": "ES256", "jwk": key_pair.public_key_jwk},
    )
    with pytest.raises(DPoPVerificationError, match="Invalid htu"):
        await verifier.verify(bad_htu, "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_iat_type_and_replay() -> None:
    key_pair = DPoPKeyPair.generate("ES256")
    verifier = DPoPProofVerifier(jti_store=InMemoryJTIReplayStore())

    bad_iat = key_pair.sign_dpop_jwt(
        payload={"jti": "j", "htm": "GET", "htu": "https://example.com/x", "iat": "x"},
        headers={"typ": "dpop+jwt", "alg": "ES256", "jwk": key_pair.public_key_jwk},
    )
    with pytest.raises(DPoPVerificationError, match="Invalid iat"):
        await verifier.verify(bad_iat, "GET", "https://example.com/x")

    gen = DPoPProofGeneratorImpl(key_pair)
    proof = gen.generate_proof("GET", "https://example.com/x")
    await verifier.verify(proof, "GET", "https://example.com/x")
    with pytest.raises(DPoPVerificationError, match="Replay"):
        await verifier.verify(proof, "GET", "https://example.com/x")


@pytest.mark.anyio
async def test_verify_rejects_ath_and_jkt_mismatch() -> None:
    key_pair = DPoPKeyPair.generate("ES256")
    gen = DPoPProofGeneratorImpl(key_pair)
    verifier = DPoPProofVerifier()

    proof = gen.generate_proof("GET", "https://example.com/x", credential="token-a")
    with pytest.raises(DPoPVerificationError, match="ath mismatch"):
        await verifier.verify(proof, "GET", "https://example.com/x", access_token="token-b")

    proof2 = gen.generate_proof("GET", "https://example.com/x")
    with pytest.raises(DPoPVerificationError, match="jkt mismatch"):
        await verifier.verify(proof2, "GET", "https://example.com/x", expected_jkt="wrong")
