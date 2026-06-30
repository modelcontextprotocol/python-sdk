"""Unit tests for `mcp.server.request_state`: codec, security policy, and default principal binding."""

import base64
import string
from collections.abc import Callable
from typing import Any, cast

import pytest
from inline_snapshot import snapshot

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from mcp.server.context import ServerRequestContext
from mcp.server.request_state import (
    AESGCMRequestStateCodec,
    InvalidRequestState,
    RequestStateSecurity,
    authenticated_principal,
)

_TOKEN_PREFIX = "v1."
_KID_LEN = 4
_NONCE_LEN = 12
_GCM_TAG_LEN = 16
_BODY_FLOOR = _KID_LEN + _NONCE_LEN + _GCM_TAG_LEN
_B64URL_ALPHABET = set(string.ascii_letters + string.digits + "-_")

_KEY_A = b"a" * 32
_KEY_B = b"b" * 32
_KEY_OLD = b"o" * 32
_KEY_NEW = b"n" * 32

# Distinctive plaintext: opacity and log-secrecy assertions search for it.
_PAYLOAD = b"sentinel-plaintext-3f9c"
# `InvalidRequestState` messages are short log-only reason codes, never payload.
_REASON_CODE_MAX_LEN = 40


def _b64u_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode_body(token: str) -> bytes:
    body = token.removeprefix(_TOKEN_PREFIX)
    return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))


def _flip_body_byte(token: str, index: int) -> str:
    raw = bytearray(_decode_body(token))
    raw[index] ^= 0xFF
    return _TOKEN_PREFIX + _b64u_nopad(bytes(raw))


def _flip_prefix_char(token: str) -> str:
    return "x" + token[1:]


def _flip_kid_byte(token: str) -> str:
    return _flip_body_byte(token, 0)


def _flip_nonce_byte(token: str) -> str:
    return _flip_body_byte(token, _KID_LEN)


def _flip_ciphertext_byte(token: str) -> str:
    return _flip_body_byte(token, _KID_LEN + _NONCE_LEN)


def _flip_tag_byte(token: str) -> str:
    return _flip_body_byte(token, -1)


def _inject_junk_chars(body: str) -> str:
    return body[:10] + "!@\n*" + body[10:]


def _append_newline(body: str) -> str:
    return body + "\n"


def _append_padding(body: str) -> str:
    return body + "=" * (-len(body) % 4 or 4)


def _bare_context() -> ServerRequestContext[Any, Any]:
    return ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
    )


class _StaticCodec:
    """Minimal `RequestStateCodec` stand-in for policy tests; no real crypto."""

    def seal(self, payload: bytes) -> str:
        return payload.hex()

    def unseal(self, token: str) -> bytes:
        return bytes.fromhex(token)


# -- AESGCMRequestStateCodec --------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"plain ascii state", id="ascii"),
        pytest.param("ünïcødé – 状態".encode(), id="multi-byte-utf8"),
        pytest.param(bytes(range(256)), id="raw-binary"),
        pytest.param(bytes(range(256)) * 256, id="64KiB"),
    ],
)
def test_seal_unseal_round_trips_any_payload(payload: bytes) -> None:
    """SDK-defined: the codec is byte-transparent, so any payload survives seal/unseal unchanged."""
    codec = AESGCMRequestStateCodec([_KEY_A])
    assert codec.unseal(codec.seal(payload)) == payload


def test_a_sealed_token_is_v1_plus_unpadded_b64url_over_kid_nonce_and_ciphertext() -> None:
    """SDK-defined token format: "v1." plus unpadded base64url over kid(4) || nonce(12) || ciphertext+tag."""
    token = AESGCMRequestStateCodec([_KEY_A]).seal(_PAYLOAD)
    assert token.startswith(_TOKEN_PREFIX)
    body = token.removeprefix(_TOKEN_PREFIX)
    assert "=" not in body
    assert set(body) <= _B64URL_ALPHABET
    assert len(_decode_body(token)) == _KID_LEN + _NONCE_LEN + len(_PAYLOAD) + _GCM_TAG_LEN


def test_two_seals_of_the_same_payload_produce_distinct_tokens_that_both_unseal() -> None:
    """SDK-defined: every seal draws a fresh nonce, so identical payloads yield distinct tokens that both verify."""
    codec = AESGCMRequestStateCodec([_KEY_A])
    first = codec.seal(_PAYLOAD)
    second = codec.seal(_PAYLOAD)
    assert first != second
    assert codec.unseal(first) == _PAYLOAD
    assert codec.unseal(second) == _PAYLOAD


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(_flip_prefix_char, id="prefix-char"),
        pytest.param(_flip_kid_byte, id="kid-byte"),
        pytest.param(_flip_nonce_byte, id="nonce-byte"),
        pytest.param(_flip_ciphertext_byte, id="ciphertext-byte"),
        pytest.param(_flip_tag_byte, id="tag-byte"),
    ],
)
def test_a_token_corrupted_in_any_region_is_rejected_without_echoing_the_payload(
    corrupt: Callable[[str], str],
) -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): any corrupted token region is rejected."""
    codec = AESGCMRequestStateCodec([_KEY_A])
    token = codec.seal(_PAYLOAD)
    with pytest.raises(InvalidRequestState) as exc:
        codec.unseal(corrupt(token))
    message = str(exc.value)
    assert len(message) <= _REASON_CODE_MAX_LEN
    assert _PAYLOAD.decode() not in message


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("", id="empty-string"),
        pytest.param(_b64u_nopad(b"\x00" * 64), id="missing-prefix"),
        pytest.param(_TOKEN_PREFIX + "!!!not-base64!!!", id="garbage-after-prefix"),
        pytest.param(_TOKEN_PREFIX + _b64u_nopad(b"\x00" * (_BODY_FLOOR - 1)), id="below-floor"),
    ],
)
def test_a_structurally_malformed_token_is_rejected(token: str) -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): tokens this codec never minted fail."""
    with pytest.raises(InvalidRequestState):
        AESGCMRequestStateCodec([_KEY_A]).unseal(token)


def test_a_token_minted_under_a_key_outside_the_ring_is_rejected_as_unknown_key() -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): a foreign-key token fails as "unknown key"."""
    token = AESGCMRequestStateCodec([_KEY_A]).seal(_PAYLOAD)
    with pytest.raises(InvalidRequestState) as exc:
        AESGCMRequestStateCodec([_KEY_B]).unseal(token)
    assert str(exc.value) == "unknown key"


@pytest.mark.parametrize(
    "ring",
    [
        pytest.param([_KEY_OLD, _KEY_NEW], id="rotation-phase-1"),
        pytest.param([_KEY_NEW, _KEY_OLD], id="rotation-phase-2"),
    ],
)
def test_a_token_minted_under_the_old_key_unseals_under_any_ring_containing_it(ring: list[bytes]) -> None:
    """SDK-defined rotation: every ring key verifies, so old-key state survives both rollout phases."""
    token = AESGCMRequestStateCodec([_KEY_OLD]).seal(_PAYLOAD)
    assert AESGCMRequestStateCodec(ring).unseal(token) == _PAYLOAD


def test_the_first_ring_key_mints_and_later_ring_keys_only_verify() -> None:
    """SDK-defined rotation: keys[0] is the minter, so [new, old] state verifies under [new] but not [old]."""
    token = AESGCMRequestStateCodec([_KEY_NEW, _KEY_OLD]).seal(_PAYLOAD)
    assert AESGCMRequestStateCodec([_KEY_NEW]).unseal(token) == _PAYLOAD
    with pytest.raises(InvalidRequestState):
        AESGCMRequestStateCodec([_KEY_OLD]).unseal(token)


def test_a_token_minted_under_a_retired_key_is_rejected() -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): retired-key state fails verification."""
    token = AESGCMRequestStateCodec([_KEY_OLD]).seal(_PAYLOAD)
    with pytest.raises(InvalidRequestState):
        AESGCMRequestStateCodec([_KEY_NEW]).unseal(token)


def test_an_empty_key_ring_is_rejected_at_construction() -> None:
    """SDK-defined: an empty ring is a configuration error caught at construction."""
    with pytest.raises(ValueError) as exc:
        AESGCMRequestStateCodec([])
    assert str(exc.value) == snapshot("AESGCMRequestStateCodec requires at least one key")


def test_a_key_shorter_than_32_bytes_is_rejected_with_generation_guidance() -> None:
    """SDK-defined: keys must carry at least 32 bytes; the error includes generation guidance."""
    with pytest.raises(ValueError) as exc:
        AESGCMRequestStateCodec([b"k" * 31])
    assert str(exc.value) == snapshot(
        "request-state keys must be at least 32 bytes of secret randomness; keys[0] is 31 bytes. "
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
    )


def test_a_duplicate_key_in_the_ring_is_rejected_at_construction() -> None:
    """SDK-defined: duplicate ring keys are a rotation mistake caught at construction."""
    with pytest.raises(ValueError) as exc:
        AESGCMRequestStateCodec([_KEY_A, _KEY_A])
    assert str(exc.value) == snapshot("keys[1] duplicates an earlier ring key")


def test_a_non_key_typed_ring_entry_is_rejected_naming_its_index_and_type() -> None:
    """SDK-defined: a non-key ring entry raises a TypeError naming its index and type, in codec and policy."""
    with pytest.raises(TypeError) as exc:
        AESGCMRequestStateCodec([_KEY_A, cast("Any", 32)])
    assert str(exc.value) == snapshot("request-state keys must be bytes, bytearray, or str; keys[1] is int")
    with pytest.raises(TypeError) as exc:
        RequestStateSecurity(keys=[cast("Any", 32)])
    assert str(exc.value) == snapshot("request-state keys must be bytes, bytearray, or str; keys[0] is int")


def test_a_mixed_ring_of_bytes_bytearray_and_str_entries_still_works() -> None:
    """SDK-defined: bytes, bytearray, and str keys interoperate in one ring."""
    codec = AESGCMRequestStateCodec([_KEY_A, bytearray(_KEY_B), "c" * 32])
    assert codec.unseal(codec.seal(_PAYLOAD)) == _PAYLOAD
    assert codec.unseal(AESGCMRequestStateCodec([bytearray(_KEY_B)]).seal(_PAYLOAD)) == _PAYLOAD
    assert codec.unseal(AESGCMRequestStateCodec(["c" * 32]).seal(_PAYLOAD)) == _PAYLOAD


def test_a_str_key_is_equivalent_to_its_utf8_bytes_form() -> None:
    """SDK-defined: a str key is utf-8 encoded, so it is the same ring key as its bytes spelling."""
    token = AESGCMRequestStateCodec(["k" * 32]).seal(_PAYLOAD)
    assert AESGCMRequestStateCodec([b"k" * 32]).unseal(token) == _PAYLOAD


def test_bytearray_key_material_is_copied_at_construction() -> None:
    """SDK-defined: key bytes are copied at construction; mutating the caller's bytearray later has no effect."""
    material = bytearray(b"m" * 32)
    codec = AESGCMRequestStateCodec([cast("Any", material)])
    minted_before_mutation = codec.seal(_PAYLOAD)
    material[:] = b"X" * 32
    assert codec.unseal(minted_before_mutation) == _PAYLOAD
    assert AESGCMRequestStateCodec([b"m" * 32]).unseal(codec.seal(_PAYLOAD)) == _PAYLOAD


def test_the_token_reveals_the_payload_neither_in_its_text_nor_its_decoded_bytes() -> None:
    """SDK-defined: the token is encrypted, not merely signed, so the plaintext appears nowhere in it."""
    token = AESGCMRequestStateCodec([_KEY_A]).seal(_PAYLOAD)
    assert _PAYLOAD.decode() not in token
    assert _b64u_nopad(_PAYLOAD) not in token
    assert _PAYLOAD.hex() not in token
    assert _PAYLOAD not in _decode_body(token)


def test_every_substitution_of_the_final_token_character_is_rejected() -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): canonical decoding
    rejects every final-character substitution despite base64 don't-care padding bits."""
    codec = AESGCMRequestStateCodec([_KEY_A])
    body = codec.seal(_PAYLOAD).removeprefix(_TOKEN_PREFIX)
    substitutions = [c for c in sorted(_B64URL_ALPHABET) if c != body[-1]]
    assert len(substitutions) == 63
    for c in substitutions:
        with pytest.raises(InvalidRequestState):
            codec.unseal(_TOKEN_PREFIX + body[:-1] + c)


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(_inject_junk_chars, id="junk-chars-injected"),
        pytest.param(_append_newline, id="newline-appended"),
        pytest.param(_append_padding, id="padding-appended"),
    ],
)
def test_a_non_canonical_token_body_is_rejected(mangle: Callable[[str], str]) -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): lax-decoder aliases of a token are rejected."""
    codec = AESGCMRequestStateCodec([_KEY_A])
    body = codec.seal(_PAYLOAD).removeprefix(_TOKEN_PREFIX)
    with pytest.raises(InvalidRequestState):
        codec.unseal(_TOKEN_PREFIX + mangle(body))


def test_a_token_reprefixed_to_a_future_format_version_is_rejected() -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): the prefix is tag-bound; "v2." replay fails."""
    codec = AESGCMRequestStateCodec([_KEY_A])
    token = codec.seal(_PAYLOAD)
    with pytest.raises(InvalidRequestState):
        codec.unseal("v2." + token.removeprefix(_TOKEN_PREFIX))


def test_a_kid_transplanted_onto_another_tokens_body_is_rejected() -> None:
    """Spec-mandated (basic/patterns/mrtr, server requirement 4): the kid is tag-bound; transplanting it fails."""
    raw_a = _decode_body(AESGCMRequestStateCodec([_KEY_A]).seal(_PAYLOAD))
    raw_b = _decode_body(AESGCMRequestStateCodec([_KEY_B]).seal(_PAYLOAD))
    assert raw_a[:_KID_LEN] != raw_b[:_KID_LEN]
    transplanted = _TOKEN_PREFIX + _b64u_nopad(raw_a[:_KID_LEN] + raw_b[_KID_LEN:])
    with pytest.raises(InvalidRequestState):
        AESGCMRequestStateCodec([_KEY_A, _KEY_B]).unseal(transplanted)


# -- RequestStateSecurity -----------------------------------------------------


def test_keys_and_codec_together_are_rejected_at_policy_construction() -> None:
    """SDK-defined: keys= and codec= are mutually exclusive."""
    with pytest.raises(ValueError) as exc:
        RequestStateSecurity(keys=[_KEY_A], codec=_StaticCodec())
    assert str(exc.value) == snapshot("RequestStateSecurity takes exactly one of keys= or codec=")


def test_a_policy_with_neither_keys_nor_codec_is_rejected() -> None:
    """SDK-defined: a policy must name its codec; opting out means omitting `request_state_security=` entirely."""
    with pytest.raises(ValueError) as exc:
        RequestStateSecurity()
    assert str(exc.value) == snapshot("RequestStateSecurity takes exactly one of keys= or codec=")


@pytest.mark.parametrize(
    "ttl",
    [
        pytest.param(0.0, id="zero"),
        pytest.param(-600.0, id="negative"),
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="inf"),
    ],
)
def test_a_non_positive_or_non_finite_ttl_is_rejected_at_policy_construction(ttl: float) -> None:
    """SDK-defined: zero, negative, NaN, and infinite ttl fail at construction for keys and ephemeral() alike."""
    with pytest.raises(ValueError, match="positive finite"):
        RequestStateSecurity(keys=[_KEY_A], ttl=ttl)
    with pytest.raises(ValueError, match="positive finite"):
        RequestStateSecurity.ephemeral(ttl=ttl)


def test_keys_produce_a_working_built_in_codec_on_the_policy() -> None:
    """SDK-defined: keys=[...] builds the built-in AES-GCM codec, exposed on .codec."""
    security = RequestStateSecurity(keys=[_KEY_A])
    assert isinstance(security.codec, AESGCMRequestStateCodec)
    assert security.codec.unseal(security.codec.seal(_PAYLOAD)) == _PAYLOAD


def test_a_custom_codec_is_stored_on_the_policy_as_is() -> None:
    """SDK-defined: codec=... stores the caller's object unwrapped."""
    codec = _StaticCodec()
    security = RequestStateSecurity(codec=codec)
    assert security.codec is codec
    assert codec.unseal(codec.seal(_PAYLOAD)) == _PAYLOAD


def test_ephemeral_policies_are_protected_and_mutually_unintelligible() -> None:
    """SDK-defined: ephemeral() protects under a process-local key, so a sibling instance rejects its tokens."""
    first = RequestStateSecurity.ephemeral()
    second = RequestStateSecurity.ephemeral()
    token = first.codec.seal(_PAYLOAD)
    assert first.codec.unseal(token) == _PAYLOAD
    with pytest.raises(InvalidRequestState):
        second.codec.unseal(token)


def test_the_policy_stores_an_explicit_audience_and_defaults_to_none() -> None:
    """SDK-defined: audience is stored as given; None defers to the server tier's `default_audience`."""
    assert RequestStateSecurity(keys=[_KEY_A]).audience is None
    assert RequestStateSecurity(keys=[_KEY_A], audience="svc").audience == "svc"
    assert RequestStateSecurity.ephemeral(audience="svc").audience == "svc"


def test_the_default_principal_binding_is_authenticated_principal() -> None:
    """SDK-defined: an unconfigured policy binds state to the authenticated OAuth client by default."""
    assert RequestStateSecurity(keys=[_KEY_A]).bind_principal is authenticated_principal


def test_an_explicit_principal_binding_callable_is_stored() -> None:
    """SDK-defined: a custom bind_principal callable is stored as given."""

    def tenant_binding(ctx: ServerRequestContext[Any, Any]) -> str | None:
        return "tenant-1"

    security = RequestStateSecurity(keys=[_KEY_A], bind_principal=tenant_binding)
    assert security.bind_principal is tenant_binding
    assert tenant_binding(_bare_context()) == "tenant-1"


# -- authenticated_principal ----------------------------------------------------


def test_authenticated_principal_is_none_without_an_auth_context() -> None:
    """SDK-defined: without an auth context the default binding derives no principal."""
    assert authenticated_principal(_bare_context()) is None


def test_authenticated_principal_returns_the_access_tokens_client_id() -> None:
    """SDK-defined: with an access token in the auth context, the default binding is its client_id."""
    user = AuthenticatedUser(AccessToken(token="at-1", client_id="client-123", scopes=[]))
    reset = auth_context_var.set(user)
    try:
        assert authenticated_principal(_bare_context()) == "client-123"
    finally:
        auth_context_var.reset(reset)
